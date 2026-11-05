
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models

from app.core.database import Base
from app.models import Competition, Stock
from app.services.trading import autonomous_trading_service as service_module
from app.services.trading.autonomous_trading_service import (
    AutonomousTradingService,
)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    yield testing_session_local

    engine.dispose()


@pytest.fixture
def autonomous_setup(session_factory):
    with session_factory() as db:
        spy = Stock(
            symbol="SPY",
            name="SPDR S&P 500 ETF",
            exchange="NYSE",
            asset_type="etf",
            is_active=True,
        )

        db.add(spy)
        db.flush()

        competition = Competition(
            name="Autonomous Trading Test",
            status="active",
            initial_cash=Decimal("10000"),
            duration_days=90,
            benchmark_stock_id=spy.id,
            started_at=datetime(
                2026, 10, 27, 12, 0,
                tzinfo=timezone.utc,
            ),
        )

        db.add(competition)
        db.commit()

        return competition.id


def create_service(
    session_factory,
    execute_orders_fn=None,
):
    return AutonomousTradingService(
        client=Mock(),
        recovery_service=Mock(),
        session_factory=session_factory,
        execute_orders_fn=(
            execute_orders_fn or Mock(return_value=[])
        ),
    )


def test_complete_sessions_skip_ingestion_and_reach_recovery(
    session_factory,
    autonomous_setup,
    monkeypatch,
):
    sessions = [
        date(2026, 10, 28),
        date(2026, 10, 29),
    ]

    monkeypatch.setattr(
        service_module,
        "get_completed_market_sessions",
        lambda started_at: sessions,
    )

    readiness = Mock(
        return_value={
            "status": "complete",
            "missing_symbols": [],
        }
    )

    ingestion = Mock()

    monkeypatch.setattr(
        service_module,
        "get_competition_session_data_status",
        readiness,
    )

    monkeypatch.setattr(
        service_module,
        "ingest_competition_session",
        ingestion,
    )

    execute_orders = Mock(return_value=[])
    autonomous = create_service(
        session_factory,
        execute_orders,
    )

    result = autonomous.run_competition(
        autonomous_setup,
    )

    assert result["sessions_found"] == 2
    assert result["sessions_ready"] == 2
    assert result["blocked_session"] is None

    ingestion.assert_not_called()
    assert execute_orders.call_count == 1

    autonomous.recovery_service.recover_competition.assert_called_once_with(
        competition_id=autonomous_setup,
        ready_sessions=set(sessions),
    )


def test_incomplete_session_stops_later_sessions(
    session_factory,
    autonomous_setup,
    monkeypatch,
):
    sessions = [
        date(2026, 10, 28),
        date(2026, 10, 29),
        date(2026, 10, 30),
    ]

    status_by_date = {
        date(2026, 10, 28): "complete",
        date(2026, 10, 29): "incomplete",
        date(2026, 10, 30): "complete",
    }

    monkeypatch.setattr(
        service_module,
        "get_completed_market_sessions",
        lambda started_at: sessions,
    )

    readiness = Mock(
        side_effect=lambda db, competition_id, session_date: {
            "status": status_by_date[session_date],
            "missing_symbols": [],
        }
    )

    ingestion = Mock(
        return_value={
            "status": "incomplete",
            "missing_symbols": ["NVDA"],
        }
    )

    monkeypatch.setattr(
        service_module,
        "get_competition_session_data_status",
        readiness,
    )

    monkeypatch.setattr(
        service_module,
        "ingest_competition_session",
        ingestion,
    )

    execute_orders = Mock(return_value=[])
    autonomous = create_service(
        session_factory,
        execute_orders,
    )

    result = autonomous.run_competition(
        autonomous_setup,
    )

    assert result["sessions_ready"] == 1
    assert result["blocked_session"] == "2026-10-29"

    assert [
        call.kwargs["session_date"]
        for call in readiness.call_args_list
    ] == [
        date(2026, 10, 28),
        date(2026, 10, 29),
        date(2026, 10, 29),
    ]

    ingestion.assert_called_once()
    # Do not execute live orders when the newest session is incomplete.
    execute_orders.assert_not_called()

    autonomous.recovery_service.recover_competition.assert_called_once_with(
        competition_id=autonomous_setup,
        ready_sessions={date(2026, 10, 28)},
    )


def test_missing_data_is_ingested_and_rechecked(
    session_factory,
    autonomous_setup,
    monkeypatch,
):
    trading_date = date(2026, 10, 28)

    monkeypatch.setattr(
        service_module,
        "get_completed_market_sessions",
        lambda started_at: [trading_date],
    )

    readiness = Mock(
        side_effect=[
            {
                "status": "incomplete",
                "missing_symbols": ["NVDA"],
            },
            {
                "status": "complete",
                "missing_symbols": [],
            },
        ]
    )

    ingestion = Mock(
        return_value={
            "status": "complete",
            "symbols_requested": 31,
            "symbols_available": 31,
        }
    )

    monkeypatch.setattr(
        service_module,
        "get_competition_session_data_status",
        readiness,
    )

    monkeypatch.setattr(
        service_module,
        "ingest_competition_session",
        ingestion,
    )

    autonomous = create_service(session_factory)

    result = autonomous.run_competition(
        autonomous_setup,
    )

    assert result["sessions_ready"] == 1
    assert result["blocked_session"] is None

    assert ingestion.call_count == 1
    assert readiness.call_count == 2

    autonomous.recovery_service.recover_competition.assert_called_once_with(
        competition_id=autonomous_setup,
        ready_sessions={trading_date},
    )


def test_one_competition_failure_does_not_stop_others(
    session_factory,
):
    with session_factory() as db:
        spy = Stock(
            symbol="SPY",
            name="SPDR S&P 500 ETF",
            exchange="NYSE",
            asset_type="etf",
            is_active=True,
        )

        db.add(spy)
        db.flush()

        competition_ids = []

        for name in ["Competition A", "Competition B"]:
            competition = Competition(
                name=name,
                status="active",
                initial_cash=Decimal("10000"),
                duration_days=90,
                benchmark_stock_id=spy.id,
                started_at=datetime(
                    2026, 10, 27, 12, 0,
                    tzinfo=timezone.utc,
                ),
            )

            db.add(competition)
            db.flush()
            competition_ids.append(competition.id)

        db.commit()

    autonomous = create_service(session_factory)

    def process_competition(competition_id):
        if competition_id == competition_ids[0]:
            raise RuntimeError("Simulated competition failure.")

        return {
            "competition_id": str(competition_id),
            "sessions_ready": 1,
        }

    autonomous.run_competition = Mock(
        side_effect=process_competition,
    )

    result = autonomous.run_all_active_competitions()

    assert result["total_competitions"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1

    statuses = {
        item["competition_id"]: item["status"]
        for item in result["results"]
    }

    assert statuses[str(competition_ids[0])] == "failed"
    assert statuses[str(competition_ids[1])] == "succeeded"


def test_competitions_complete_at_duration_boundary(
    session_factory,
    autonomous_setup,
):
    autonomous = create_service(session_factory)
    autonomous.run_competition = Mock(
        return_value={"competition_id": str(autonomous_setup)}
    )

    before_end = datetime(
        2027, 1, 25, 11, 59, 59,
        tzinfo=timezone.utc,
    )
    result = autonomous.run_all_active_competitions(now=before_end)

    assert result["total_competitions"] == 1
    assert result["completed_competitions"] == 0
    autonomous.run_competition.assert_called_once_with(
        competition_id=autonomous_setup
    )

    end_time = datetime(
        2027, 1, 25, 12, 0,
        tzinfo=timezone.utc,
    )
    result = autonomous.run_all_active_competitions(now=end_time)

    assert result["total_competitions"] == 0
    assert result["completed_competitions"] == 1
    autonomous.run_competition.assert_called_once()

    with session_factory() as db:
        competition = db.get(Competition, autonomous_setup)

        assert competition.status == "completed"
        assert competition.completed_at.replace(
            tzinfo=timezone.utc
        ) == end_time

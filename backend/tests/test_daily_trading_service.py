
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models

from app.core.database import Base
from app.models import (
    Agent,
    AgentDailyRun,
    Competition,
    MarketSessionMonitor,
    Stock,
)
from app.schemas.agent_decision import AgentDecision
from app.services.trading.daily_trading_service import (
    DailyTradingCoordinator,
    DailyTradingError,
)


TRADING_DATE = date(2026, 10, 30)


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
def trading_setup(session_factory):
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
            name="Daily Trading Test",
            status="active",
            initial_cash=Decimal("10000"),
            duration_days=90,
            benchmark_stock_id=spy.id,
        )

        db.add(competition)
        db.flush()

        momentum = Agent(
            competition_id=competition.id,
            name="Momentum",
            strategy_type="momentum",
            status="active",
        )

        warren = Agent(
            competition_id=competition.id,
            name="Warren",
            strategy_type="buy_and_hold",
            status="active",
        )

        db.add_all([momentum, warren])
        db.commit()

        return {
            "competition_id": competition.id,
            "momentum_id": momentum.id,
            "warren_id": warren.id,
        }


@pytest.fixture
def successful_decision():
    return AgentDecision(
        as_of_date=TRADING_DATE,
        summary="No suitable trading opportunities today.",
        decisions=[],
    )


@pytest.fixture
def mock_calendar(monkeypatch):
    from app.services.trading import daily_trading_service

    monkeypatch.setattr(
        daily_trading_service,
        "get_market_session_close",
        lambda session_date: datetime(
            2026, 10, 30, 20, 0, tzinfo=timezone.utc
        ),
    )


def test_successfully_processes_all_active_agents(
    session_factory,
    trading_setup,
    successful_decision,
    mock_calendar,
):
    orchestrator = Mock()

    orchestrator.generate_and_submit_agent_orders.return_value = (
        successful_decision,
        [],
    )

    coordinator = DailyTradingCoordinator(
        decision_orchestrator=orchestrator,
        session_factory=session_factory,
    )

    result = coordinator.run_competition_for_session(
        competition_id=trading_setup["competition_id"],
        trading_date=TRADING_DATE,
    )

    assert result["total_agents"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["skipped"] == 0

    assert orchestrator.generate_and_submit_agent_orders.call_count == 2

    with session_factory() as db:
        runs = db.scalars(
            select(AgentDailyRun).where(
                AgentDailyRun.competition_id
                == trading_setup["competition_id"]
            )
        ).all()

        assert len(runs) == 2
        assert all(run.status == "succeeded" for run in runs)
        assert all(run.orders_created == 0 for run in runs)
        assert all(run.decision is not None for run in runs)
        assert all(run.completed_at is not None for run in runs)


def test_one_agent_failure_does_not_stop_other_agents(
    session_factory,
    trading_setup,
    successful_decision,
    mock_calendar,
):
    orchestrator = Mock()

    def generate_decision(
        db,
        competition_id,
        agent_id,
        as_of_date,
    ):
        if agent_id == trading_setup["momentum_id"]:
            raise RuntimeError("Simulated agent failure")

        return successful_decision, []

    orchestrator.generate_and_submit_agent_orders.side_effect = (
        generate_decision
    )

    coordinator = DailyTradingCoordinator(
        decision_orchestrator=orchestrator,
        session_factory=session_factory,
    )

    result = coordinator.run_competition_for_session(
        competition_id=trading_setup["competition_id"],
        trading_date=TRADING_DATE,
    )

    assert result["total_agents"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1

    with session_factory() as db:
        runs = db.scalars(
            select(AgentDailyRun).where(
                AgentDailyRun.competition_id
                == trading_setup["competition_id"]
            )
        ).all()

        runs_by_agent = {
            run.agent_id: run
            for run in runs
        }

        failed_run = runs_by_agent[
            trading_setup["momentum_id"]
        ]

        successful_run = runs_by_agent[
            trading_setup["warren_id"]
        ]

        assert failed_run.status == "failed"
        assert "Simulated agent failure" in failed_run.error_message

        assert successful_run.status == "succeeded"


def test_existing_daily_run_is_skipped(
    session_factory,
    trading_setup,
    successful_decision,
    mock_calendar,
):
    with session_factory() as db:
        existing_run = AgentDailyRun(
            competition_id=trading_setup["competition_id"],
            agent_id=trading_setup["momentum_id"],
            trading_date=TRADING_DATE,
            status="succeeded",
            orders_created=0,
            decision=successful_decision.model_dump(mode="json"),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )

        db.add(existing_run)
        db.commit()

    orchestrator = Mock()
    orchestrator.generate_and_submit_agent_orders.return_value = (
        successful_decision,
        [],
    )

    coordinator = DailyTradingCoordinator(
        decision_orchestrator=orchestrator,
        session_factory=session_factory,
    )

    result = coordinator.run_competition_for_session(
        competition_id=trading_setup["competition_id"],
        trading_date=TRADING_DATE,
    )

    assert result["total_agents"] == 2
    assert result["skipped"] == 1
    assert result["succeeded"] == 1

    # Only Warren should have been processed.
    assert orchestrator.generate_and_submit_agent_orders.call_count == 1

    call_agent_id = (
        orchestrator.generate_and_submit_agent_orders.call_args.kwargs[
            "agent_id"
        ]
    )

    assert call_agent_id == trading_setup["warren_id"]


def test_rejects_non_trading_date(
    session_factory,
    trading_setup,
    monkeypatch,
):
    from app.services.trading import daily_trading_service

    monkeypatch.setattr(
        daily_trading_service,
        "get_market_session_close",
        lambda session_date: None,
    )

    coordinator = DailyTradingCoordinator(
        decision_orchestrator=Mock(),
        session_factory=session_factory,
    )

    with pytest.raises(
        DailyTradingError,
        match="not an NYSE trading session",
    ):
        coordinator.run_competition_for_session(
            competition_id=trading_setup["competition_id"],
            trading_date=date(2026, 10, 31),
        )


def test_rejects_session_that_has_not_closed(
    session_factory,
    trading_setup,
    monkeypatch,
):
    from app.services.trading import daily_trading_service

    monkeypatch.setattr(
        daily_trading_service,
        "get_market_session_close",
        lambda session_date: datetime(
            2099, 10, 30, 20, 0, tzinfo=timezone.utc
        ),
    )

    coordinator = DailyTradingCoordinator(
        decision_orchestrator=Mock(),
        session_factory=session_factory,
    )

    with pytest.raises(
        DailyTradingError,
        match="has not closed yet",
    ):
        coordinator.run_competition_for_session(
            competition_id=trading_setup["competition_id"],
            trading_date=TRADING_DATE,
        )


def test_rejects_inactive_competition(
    session_factory,
    trading_setup,
    mock_calendar,
):
    with session_factory() as db:
        competition = db.get(
            Competition,
            trading_setup["competition_id"],
        )

        competition.status = "pending"
        db.commit()

    coordinator = DailyTradingCoordinator(
        decision_orchestrator=Mock(),
        session_factory=session_factory,
    )

    with pytest.raises(
        DailyTradingError,
        match="Only active competitions",
    ):
        coordinator.run_competition_for_session(
            competition_id=trading_setup["competition_id"],
            trading_date=TRADING_DATE,
        )

def test_recovery_only_submits_orders_for_latest_session(
    session_factory,
    trading_setup,
    monkeypatch,
):
    from datetime import datetime, timezone
    from unittest.mock import Mock

    from app.models import Competition
    from app.services.trading import recovery_service
    from app.services.trading.recovery_service import (
        DailyTradingRecoveryService,
    )

    historical_sessions = [
        date(2026, 10, 28),
        date(2026, 10, 29),
        date(2026, 10, 30),
    ]

    with session_factory() as db:
        competition = db.get(
            Competition,
            trading_setup["competition_id"],
        )
        competition.started_at = datetime(
            2026, 10, 27, 12, 0, tzinfo=timezone.utc
        )
        db.commit()
        db.add(
            MarketSessionMonitor(
                session_date=date(2026, 10, 30),
                status="completed",
                observed_at=datetime(
                    2026, 10, 30, 13, 0,
                    tzinfo=timezone.utc,
                ),
                last_heartbeat_at=datetime(
                    2026, 10, 30, 21, 15,
                    tzinfo=timezone.utc,
                ),
                completed_at=datetime(
                    2026, 10, 30, 21, 16,
                    tzinfo=timezone.utc,
                ),
            )
        )
        db.commit()

    monkeypatch.setattr(
        recovery_service,
        "get_completed_market_sessions",
        lambda started_at: historical_sessions,
    )

    coordinator = Mock()
    coordinator.run_competition_for_session.return_value = {
        "succeeded": 1,
        "failed": 0,
        "skipped": 0,
    }

    recovery = DailyTradingRecoveryService(
        coordinator=coordinator,
        session_factory=session_factory,
    )

    result = recovery.recover_competition(
        competition_id=trading_setup["competition_id"],
    )

    assert result["sessions_found"] == 3
    assert result["sessions_processed"] == 3
    assert result["latest_completed_session"] == "2026-10-30"

    calls = coordinator.run_competition_for_session.call_args_list

    assert len(calls) == 3

    assert calls[0].kwargs["submit_orders"] is False
    assert calls[1].kwargs["submit_orders"] is False
    assert calls[2].kwargs["submit_orders"] is True


def test_recovery_returns_empty_result_when_no_sessions_are_completed(
    session_factory,
    trading_setup,
    monkeypatch,
):
    from datetime import datetime, timezone
    from unittest.mock import Mock

    from app.models import Competition
    from app.services.trading import recovery_service
    from app.services.trading.recovery_service import (
        DailyTradingRecoveryService,
    )

    with session_factory() as db:
        competition = db.get(
            Competition,
            trading_setup["competition_id"],
        )
        competition.started_at = datetime.now(timezone.utc)
        db.commit()

    monkeypatch.setattr(
        recovery_service,
        "get_completed_market_sessions",
        lambda started_at: [],
    )

    coordinator = Mock()

    recovery = DailyTradingRecoveryService(
        coordinator=coordinator,
        session_factory=session_factory,
    )

    result = recovery.recover_competition(
        competition_id=trading_setup["competition_id"],
    )

    assert result["sessions_found"] == 0
    assert result["sessions_processed"] == 0
    assert result["results"] == []

    coordinator.run_competition_for_session.assert_not_called()


def test_recovery_defers_latest_session_while_monitoring(
    session_factory,
    trading_setup,
    monkeypatch,
):
    from app.services.trading import recovery_service
    from app.services.trading.recovery_service import (
        DailyTradingRecoveryService,
    )

    historical_sessions = [
        date(2026, 10, 28),
        date(2026, 10, 29),
        date(2026, 10, 30),
    ]

    with session_factory() as db:
        competition = db.get(
            Competition,
            trading_setup["competition_id"],
        )
        competition.started_at = datetime(
            2026, 10, 27, 12, 0,
            tzinfo=timezone.utc,
        )

        db.add(
            MarketSessionMonitor(
                session_date=date(2026, 10, 30),
                status="monitoring",
                observed_at=datetime(
                    2026, 10, 30, 13, 0,
                    tzinfo=timezone.utc,
                ),
                last_heartbeat_at=datetime(
                    2026, 10, 30, 20, 30,
                    tzinfo=timezone.utc,
                ),
            )
        )

        db.commit()

    monkeypatch.setattr(
        recovery_service,
        "get_completed_market_sessions",
        lambda started_at: historical_sessions,
    )

    coordinator = Mock()
    coordinator.run_competition_for_session.return_value = {
        "succeeded": 1,
        "failed": 0,
        "skipped": 0,
    }

    recovery = DailyTradingRecoveryService(
        coordinator=coordinator,
        session_factory=session_factory,
    )

    result = recovery.recover_competition(
        competition_id=trading_setup["competition_id"],
    )

    assert result["sessions_found"] == 3
    assert result["sessions_processed"] == 2
    assert result["sessions_deferred"] == 1
    assert result["latest_session_monitor_status"] == "monitoring"

    calls = coordinator.run_competition_for_session.call_args_list

    assert len(calls) == 2
    assert all(
        call.kwargs["submit_orders"] is False
        for call in calls
    )

    assert all(
        call.kwargs["trading_date"] != date(2026, 10, 30)
        for call in calls
    )



@pytest.mark.parametrize(
    "monitor_status",
    ["missed", None],
)
def test_recovery_does_not_submit_orders_without_healthy_monitor(
    session_factory,
    trading_setup,
    monkeypatch,
    monitor_status,
):
    from app.services.trading import recovery_service
    from app.services.trading.recovery_service import (
        DailyTradingRecoveryService,
    )

    historical_sessions = [
        date(2026, 10, 28),
        date(2026, 10, 29),
        date(2026, 10, 30),
    ]

    with session_factory() as db:
        competition = db.get(
            Competition,
            trading_setup["competition_id"],
        )
        competition.started_at = datetime(
            2026, 10, 27, 12, 0,
            tzinfo=timezone.utc,
        )

        if monitor_status is not None:
            db.add(
                MarketSessionMonitor(
                    session_date=date(2026, 10, 30),
                    status=monitor_status,
                    observed_at=datetime(
                        2026, 10, 30, 13, 0,
                        tzinfo=timezone.utc,
                    ),
                    last_heartbeat_at=datetime(
                        2026, 10, 30, 20, 30,
                        tzinfo=timezone.utc,
                    ),
                    missed_reason=(
                        "Simulated missed session."
                        if monitor_status == "missed"
                        else None
                    ),
                )
            )

        db.commit()

    monkeypatch.setattr(
        recovery_service,
        "get_completed_market_sessions",
        lambda started_at: historical_sessions,
    )

    coordinator = Mock()
    coordinator.run_competition_for_session.return_value = {
        "succeeded": 1,
        "failed": 0,
        "skipped": 0,
    }

    recovery = DailyTradingRecoveryService(
        coordinator=coordinator,
        session_factory=session_factory,
    )

    result = recovery.recover_competition(
        competition_id=trading_setup["competition_id"],
    )

    assert result["sessions_found"] == 3
    assert result["sessions_processed"] == 3
    assert result["sessions_deferred"] == 0
    assert result["latest_session_monitor_status"] == monitor_status

    calls = coordinator.run_competition_for_session.call_args_list

    assert len(calls) == 3

    # No session is allowed to submit orders.
    assert all(
        call.kwargs["submit_orders"] is False
        for call in calls
    )
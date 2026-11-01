
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models

from app.core.database import Base
from app.models import MarketSessionMonitor
from app.services.trading import market_session_monitor_service
from app.services.trading.market_session_monitor_service import (
    MarketSessionMonitorService,
)


@pytest.fixture
def db_factory():
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

    try:
        yield testing_session_local
    finally:
        engine.dispose()


@pytest.fixture
def market_calendar(monkeypatch):
    session_date = date(2026, 11, 2)

    market_open = datetime(
        2026, 11, 2, 14, 30,
        tzinfo=timezone.utc,
    )

    market_close = datetime(
        2026, 11, 2, 21, 0,
        tzinfo=timezone.utc,
    )

    monkeypatch.setattr(
        market_session_monitor_service,
        "get_market_session_open",
        lambda requested_date: (
            market_open if requested_date == session_date else None
        ),
    )

    monkeypatch.setattr(
        market_session_monitor_service,
        "get_market_session_close",
        lambda requested_date: (
            market_close if requested_date == session_date else None
        ),
    )

    return {
        "date": session_date,
        "open": market_open,
        "close": market_close,
    }


def get_monitor(db_factory, session_date):
    with db_factory() as db:
        return db.scalar(
            select(MarketSessionMonitor).where(
                MarketSessionMonitor.session_date == session_date
            )
        )


def test_registers_session_before_market_open(
    db_factory,
    market_calendar,
):
    service = MarketSessionMonitorService(
        session_factory=db_factory,
    )

    now = datetime(
        2026, 11, 2, 13, 0,
        tzinfo=timezone.utc,
    )

    result = service.run_once(now=now)

    monitor = get_monitor(
        db_factory,
        market_calendar["date"],
    )

    assert result["status"] == "monitoring"
    assert result["action"] == "session_registered"

    assert monitor is not None
    assert monitor.status == "monitoring"
    assert monitor.observed_at.replace(
        tzinfo=timezone.utc
    ) == now

    assert monitor.last_heartbeat_at.replace(
        tzinfo=timezone.utc
    ) == now


def test_marks_session_missed_if_backend_starts_after_market_open(
    db_factory,
    market_calendar,
):
    service = MarketSessionMonitorService(
        session_factory=db_factory,
    )

    now = datetime(
        2026, 11, 2, 15, 0,
        tzinfo=timezone.utc,
    )

    result = service.run_once(now=now)

    monitor = get_monitor(
        db_factory,
        market_calendar["date"],
    )

    assert result["status"] == "missed"
    assert result["action"] == "late_start"

    assert monitor is not None
    assert monitor.status == "missed"
    assert "after market open" in monitor.missed_reason


def test_regular_heartbeat_keeps_session_monitoring(
    db_factory,
    market_calendar,
):
    service = MarketSessionMonitorService(
        session_factory=db_factory,
    )

    first_heartbeat = datetime(
        2026, 11, 2, 13, 0,
        tzinfo=timezone.utc,
    )

    second_heartbeat = first_heartbeat + timedelta(minutes=1)

    service.run_once(now=first_heartbeat)
    result = service.run_once(now=second_heartbeat)

    monitor = get_monitor(
        db_factory,
        market_calendar["date"],
    )

    assert result["status"] == "monitoring"
    assert result["action"] == "heartbeat_updated"

    assert monitor.status == "monitoring"
    assert monitor.observed_at.replace(
        tzinfo=timezone.utc
    ) == first_heartbeat

    assert monitor.last_heartbeat_at.replace(
        tzinfo=timezone.utc
    ) == second_heartbeat


def test_marks_session_missed_after_heartbeat_interruption(
    db_factory,
    market_calendar,
):
    service = MarketSessionMonitorService(
        session_factory=db_factory,
    )

    first_heartbeat = datetime(
        2026, 11, 2, 13, 0,
        tzinfo=timezone.utc,
    )

    interrupted_heartbeat = first_heartbeat + timedelta(minutes=4)

    service.run_once(now=first_heartbeat)
    result = service.run_once(now=interrupted_heartbeat)

    monitor = get_monitor(
        db_factory,
        market_calendar["date"],
    )

    assert result["status"] == "missed"
    assert result["action"] == "session_marked_missed"

    assert monitor.status == "missed"
    assert "Heartbeat interruption" in monitor.missed_reason



def test_marks_session_completed_after_execution_deadline(
    db_factory,
    market_calendar,
):
    service = MarketSessionMonitorService(
        session_factory=db_factory,
        max_heartbeat_gap=timedelta(hours=9),
    )

    first_heartbeat = datetime(
        2026, 11, 2, 13, 0,
        tzinfo=timezone.utc,
    )

    before_deadline = datetime(
        2026, 11, 2, 21, 14, 59,
        tzinfo=timezone.utc,
    )

    after_deadline = datetime(
        2026, 11, 2, 21, 15, 1,
        tzinfo=timezone.utc,
    )

    service.run_once(now=first_heartbeat)
    service.run_once(now=before_deadline)

    result = service.run_once(now=after_deadline)

    monitor = get_monitor(
        db_factory,
        market_calendar["date"],
    )

    assert result["status"] == "completed"
    assert result["action"] == "session_completed"

    assert monitor.status == "completed"
    assert monitor.completed_at is not None
    assert monitor.missed_reason is None


def test_marks_previous_unfinished_session_missed_after_restart(
    db_factory,
    market_calendar,
):
    previous_session_date = date(2026, 10, 30)

    previous_monitor = MarketSessionMonitor(
        session_date=previous_session_date,
        status="monitoring",
        observed_at=datetime(
            2026, 10, 30, 13, 0,
            tzinfo=timezone.utc,
        ),
        last_heartbeat_at=datetime(
            2026, 10, 30, 20, 0,
            tzinfo=timezone.utc,
        ),
    )

    with db_factory() as db:
        db.add(previous_monitor)
        db.commit()

    service = MarketSessionMonitorService(
        session_factory=db_factory,
    )

    # Backend resumes before the next trading day's market open.
    now = datetime(
        2026, 11, 2, 13, 0,
        tzinfo=timezone.utc,
    )

    result = service.run_once(now=now)

    old_monitor = get_monitor(
        db_factory,
        previous_session_date,
    )

    current_monitor = get_monitor(
        db_factory,
        market_calendar["date"],
    )

    assert result["status"] == "monitoring"
    assert result["action"] == "session_registered"

    assert old_monitor is not None
    assert old_monitor.status == "missed"
    assert "Backend restarted" in old_monitor.missed_reason

    assert current_monitor is not None
    assert current_monitor.status == "monitoring"
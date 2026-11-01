
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models

from app.core.database import Base
from app.models.stock_universe_snapshot import StockUniverseSnapshot
from app.services.trading.market_context_service import (
    _get_universe_snapshot,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def create_snapshot(db, as_of, status="completed"):
    snapshot = StockUniverseSnapshot(
        source="test",
        status=status,
        as_of=as_of,
        total_members=30,
    )

    db.add(snapshot)
    db.commit()

    return snapshot


def test_uses_assigned_snapshot_instead_of_newer_snapshot(db):
    older_snapshot = create_snapshot(
        db,
        datetime(2026, 10, 30, tzinfo=timezone.utc),
    )

    assigned_snapshot = create_snapshot(
        db,
        datetime(2026, 10, 31, tzinfo=timezone.utc),
    )

    competition = SimpleNamespace(
        stock_universe_snapshot_id=assigned_snapshot.id,
        started_at=datetime(2026, 10, 30, 12, tzinfo=timezone.utc),
    )

    result = _get_universe_snapshot(db, competition)

    assert result.id == assigned_snapshot.id
    assert result.id != older_snapshot.id


def test_legacy_competition_uses_latest_snapshot_before_start(db):
    older_snapshot = create_snapshot(
        db,
        datetime(2026, 10, 30, 10, tzinfo=timezone.utc),
    )

    latest_snapshot = create_snapshot(
        db,
        datetime(2026, 10, 31, 10, tzinfo=timezone.utc),
    )

    create_snapshot(
        db,
        datetime(2026, 10, 31, 12, tzinfo=timezone.utc),
    )

    competition = SimpleNamespace(
        stock_universe_snapshot_id=None,
        started_at=datetime(2026, 10, 31, 11, tzinfo=timezone.utc),
    )

    result = _get_universe_snapshot(db, competition)

    assert result.id == latest_snapshot.id
    assert result.id != older_snapshot.id


def test_legacy_competition_without_start_date_is_rejected(db):
    competition = SimpleNamespace(
        stock_universe_snapshot_id=None,
        started_at=None,
    )

    with pytest.raises(
        ValueError,
        match="start date",
    ):
        _get_universe_snapshot(db, competition)


def test_assigned_snapshot_that_is_not_completed_is_rejected(db):
    snapshot = create_snapshot(
        db,
        datetime(2026, 10, 31, tzinfo=timezone.utc),
        status="failed",
    )

    competition = SimpleNamespace(
        stock_universe_snapshot_id=snapshot.id,
        started_at=datetime(2026, 10, 31, 12, tzinfo=timezone.utc),
    )

    with pytest.raises(
        ValueError,
        match="missing or is not completed",
    ):
        _get_universe_snapshot(db, competition)


def test_missing_assigned_snapshot_is_rejected(db):
    competition = SimpleNamespace(
        stock_universe_snapshot_id=uuid4(),
        started_at=datetime(2026, 10, 31, tzinfo=timezone.utc),
    )

    with pytest.raises(
        ValueError,
        match="missing or is not completed",
    ):
        _get_universe_snapshot(db, competition)

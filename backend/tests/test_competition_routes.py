
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models

from app.core.database import Base, get_db
from app.main import app
from app.models import Competition, Stock
from app.models.stock_universe_snapshot import StockUniverseSnapshot
from app.models.stock_universe_membership import StockUniverseMembership


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


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def pending_competition(db):
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
        name="Snapshot Route Test",
        status="pending",
        initial_cash=Decimal("10000"),
        duration_days=90,
        benchmark_stock_id=spy.id,
    )

    db.add(competition)
    db.commit()

    return competition


def create_snapshot(db, member_count=30, active=True):
    snapshot = StockUniverseSnapshot(
        source="test",
        status="completed",
        as_of=datetime.now(timezone.utc),
        total_members=30,
    )

    db.add(snapshot)
    db.flush()

    stocks = []

    for index in range(member_count):
        stock = Stock(
            symbol=f"TST{index:02d}",
            name=f"Test Company {index}",
            exchange="NASDAQ",
            asset_type="stock",
            is_active=active,
        )

        db.add(stock)
        db.flush()
        stocks.append(stock)

        db.add(
            StockUniverseMembership(
                snapshot_id=snapshot.id,
                stock_id=stock.id,
                sector="Technology",
                industry="Software",
                market_cap=Decimal("1000000000"),
                sector_rank=index + 1,
            )
        )

    db.commit()

    return snapshot


def test_start_competition_assigns_valid_snapshot(
    client,
    db,
    pending_competition,
):
    snapshot = create_snapshot(db, member_count=30)

    response = client.post(
        f"/api/competitions/{pending_competition.id}/start"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "active"
    assert data["started_at"] is not None

    db.expire_all()

    updated_competition = db.scalar(
        select(Competition).where(
            Competition.id == pending_competition.id
        )
    )

    assert updated_competition.stock_universe_snapshot_id == snapshot.id


def test_start_competition_rejects_missing_snapshot(
    client,
    pending_competition,
):
    response = client.post(
        f"/api/competitions/{pending_competition.id}/start"
    )

    assert response.status_code == 409
    assert "No completed stock universe snapshot" in response.json()["detail"]


def test_start_competition_rejects_incomplete_snapshot(
    client,
    pending_competition,
    db,
):
    create_snapshot(db, member_count=29)

    response = client.post(
        f"/api/competitions/{pending_competition.id}/start"
    )

    assert response.status_code == 409
    assert "exactly 30 active stocks" in response.json()["detail"]

    db.expire_all()

    competition = db.scalar(
        select(Competition).where(
            Competition.id == pending_competition.id
        )
    )

    assert competition.status == "pending"
    assert competition.stock_universe_snapshot_id is None


def test_start_competition_rejects_inactive_snapshot_stocks(
    client,
    pending_competition,
    db,
):
    create_snapshot(db, member_count=30, active=False)

    response = client.post(
        f"/api/competitions/{pending_competition.id}/start"
    )

    assert response.status_code == 409
    assert "exactly 30 active stocks" in response.json()["detail"]

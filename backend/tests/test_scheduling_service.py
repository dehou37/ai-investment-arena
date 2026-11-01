
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models

from app.core.database import Base
from app.models import (
    Agent,
    Competition,
    Order,
    Portfolio,
    Stock,
)
from app.services.brokerage.scheduling_service import (
    schedule_orders,
    schedule_pending_orders,
)


@pytest.fixture
def db():
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

    session = testing_session_local()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def scheduling_setup(db):
    spy = Stock(
        symbol="SPY",
        name="SPDR S&P 500 ETF",
        exchange="NYSE",
        asset_type="etf",
        is_active=True,
    )

    nvda = Stock(
        symbol="NVDA",
        name="NVIDIA",
        exchange="NASDAQ",
        asset_type="stock",
        is_active=True,
    )

    db.add_all([spy, nvda])
    db.flush()

    competition = Competition(
        name="Scheduling Test",
        status="active",
        initial_cash=Decimal("10000"),
        duration_days=90,
        benchmark_stock_id=spy.id,
    )

    db.add(competition)
    db.flush()

    agent = Agent(
        competition_id=competition.id,
        name="Test Agent",
        strategy_type="buy_and_hold",
        status="active",
    )

    db.add(agent)
    db.flush()

    portfolio = Portfolio(
        agent_id=agent.id,
        cash_balance=Decimal("10000"),
    )

    db.add(portfolio)
    db.flush()

    return {
        "competition": competition,
        "agent": agent,
        "portfolio": portfolio,
        "nvda": nvda,
    }


def create_order(db, setup, submitted_at=None):
    order = Order(
        portfolio_id=setup["portfolio"].id,
        stock_id=setup["nvda"].id,
        side="buy",
        order_type="market",
        quantity=1,
        status="pending",
        submitted_at=submitted_at or datetime.now(timezone.utc),
    )

    db.add(order)
    db.flush()

    return order


def test_schedule_orders_queues_only_supplied_orders(
    db,
    scheduling_setup,
    monkeypatch,
):
    from app.services.brokerage import scheduling_service

    scheduled_time = datetime(
        2026, 11, 2, 14, 30, tzinfo=timezone.utc
    )

    monkeypatch.setattr(
        scheduling_service,
        "get_next_market_open",
        lambda submitted_at: scheduled_time,
    )

    first_order = create_order(db, scheduling_setup)
    unrelated_order = create_order(db, scheduling_setup)

    db.commit()

    result = schedule_orders(
        db=db,
        orders=[first_order],
    )

    assert len(result) == 1
    assert first_order.status == "queued"
    assert (
        first_order.scheduled_execution_at
        == scheduled_time.replace(tzinfo=None)
    )

    assert unrelated_order.status == "pending"
    assert unrelated_order.scheduled_execution_at is None


def test_schedule_orders_returns_empty_list_for_no_orders(db):
    assert schedule_orders(db=db, orders=[]) == []


def test_schedule_orders_rejects_non_pending_order(
    db,
    scheduling_setup,
):
    order = create_order(db, scheduling_setup)
    db.commit()

    order.status = "filled"
    db.commit()

    with pytest.raises(
        ValueError,
        match="is not pending",
    ):
        schedule_orders(
            db=db,
            orders=[order],
        )

    db.refresh(order)

    assert order.status == "filled"


def test_schedule_pending_orders_rejects_inactive_competition(
    db,
    scheduling_setup,
):
    scheduling_setup["competition"].status = "pending"
    db.commit()

    from fastapi import HTTPException

    with pytest.raises(
        HTTPException,
        match="Only active competitions",
    ):
        schedule_pending_orders(
            db=db,
            competition_id=scheduling_setup["competition"].id,
        )


from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models

from app.core.database import Base
from app.models import (
    Agent,
    Competition,
    Execution,
    Order,
    Portfolio,
    Position,
    Stock,
)
from app.services.brokerage import execution_service


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
def trading_setup(db):
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
        name="Execution Test",
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
    db.commit()

    return {
        "competition": competition,
        "agent": agent,
        "portfolio": portfolio,
        "nvda": nvda,
    }


@pytest.fixture
def market_session(monkeypatch):
    """
    Make the scheduled session eligible for execution
    without depending on the real exchange calendar.
    """

    now = datetime.now(timezone.utc)

    scheduled_at = now - timedelta(days=1)
    session_close = now - timedelta(minutes=1)
    next_market_open = now + timedelta(days=1)

    monkeypatch.setattr(
        execution_service,
        "get_market_session_close",
        lambda session_date: session_close,
    )

    monkeypatch.setattr(
        execution_service,
        "get_next_market_open",
        lambda timestamp: next_market_open,
    )

    return {
        "now": now,
        "scheduled_at": scheduled_at,
        "session_close": session_close,
        "next_market_open": next_market_open,
    }


@pytest.fixture
def market_bar():
    return SimpleNamespace(
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("95"),
        close=Decimal("102"),
    )


def create_queued_order(
    db,
    trading_setup,
    market_session,
    side="buy",
    quantity=1,
    order_type="market",
    limit_price=None,
):
    order = Order(
        portfolio_id=trading_setup["portfolio"].id,
        stock_id=trading_setup["nvda"].id,
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        status="queued",
        submitted_at=market_session["scheduled_at"],
        scheduled_execution_at=market_session["scheduled_at"],
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return order


def get_executions(db):
    return db.scalars(select(Execution)).all()


def test_market_buy_executes_with_slippage_and_fees(
    db,
    trading_setup,
    market_session,
    market_bar,
    monkeypatch,
):
    setup = trading_setup
    portfolio = setup["portfolio"]

    order = create_queued_order(
        db,
        setup,
        market_session,
        side="buy",
        quantity=1,
    )

    monkeypatch.setattr(
        execution_service,
        "get_session_bar",
        lambda db, order: market_bar,
    )

    result = execution_service.execute_queued_orders(
        db,
        setup["competition"].id,
    )

    execution = get_executions(db)[0]

    expected_price = Decimal("100") * (
        Decimal("1") + execution_service.MARKET_SLIPPAGE_RATE
    )
    expected_fee = expected_price * execution_service.TRADING_FEE_RATE

    assert len(result) == 1
    assert result[0].id == order.id
    assert order.status == "filled"

    assert execution.quantity == 1
    assert execution.execution_price == expected_price
    assert execution.fees == expected_fee
    assert execution.slippage == expected_price - Decimal("100")

    assert portfolio.cash_balance == (
        Decimal("10000") - expected_price - expected_fee
    )

    position = db.scalar(
        select(Position).where(
            Position.portfolio_id == portfolio.id,
            Position.stock_id == setup["nvda"].id,
        )
    )

    assert position is not None
    assert position.quantity == 1
    assert position.average_entry_price == expected_price


def test_market_sell_executes_with_slippage_and_fees(
    db,
    trading_setup,
    market_session,
    market_bar,
    monkeypatch,
):
    setup = trading_setup
    portfolio = setup["portfolio"]

    position = Position(
        portfolio_id=portfolio.id,
        stock_id=setup["nvda"].id,
        quantity=2,
        average_entry_price=Decimal("90"),
    )
    db.add(position)
    db.commit()

    order = create_queued_order(
        db,
        setup,
        market_session,
        side="sell",
        quantity=1,
    )

    monkeypatch.setattr(
        execution_service,
        "get_session_bar",
        lambda db, order: market_bar,
    )

    result = execution_service.execute_queued_orders(
        db,
        setup["competition"].id,
    )

    execution = get_executions(db)[0]

    expected_price = Decimal("100") * (
        Decimal("1") - execution_service.MARKET_SLIPPAGE_RATE
    )
    expected_fee = expected_price * execution_service.TRADING_FEE_RATE

    assert len(result) == 1
    assert order.status == "filled"

    assert execution.execution_price == expected_price
    assert execution.fees == expected_fee
    assert execution.slippage == Decimal("100") - expected_price

    assert portfolio.cash_balance == (
        Decimal("10000") + expected_price - expected_fee
    )

    db.refresh(position)
    assert position.quantity == 1


@pytest.mark.parametrize(
    "side,limit_price,expected_price,position_quantity",
    [
        ("buy", Decimal("97"), Decimal("97"), 1),
        ("buy", Decimal("105"), Decimal("100"), 1),
        ("sell", Decimal("103"), Decimal("103"), 1),
        ("sell", Decimal("95"), Decimal("100"), 1),
    ],
)
def test_limit_orders_fill_at_limit_or_better_opening_price(
    db,
    trading_setup,
    market_session,
    market_bar,
    monkeypatch,
    side,
    limit_price,
    expected_price,
    position_quantity,
):
    setup = trading_setup
    portfolio = setup["portfolio"]

    if side == "sell":
        db.add(
            Position(
                portfolio_id=portfolio.id,
                stock_id=setup["nvda"].id,
                quantity=2,
                average_entry_price=Decimal("90"),
            )
        )
        db.commit()

    order = create_queued_order(
        db,
        setup,
        market_session,
        side=side,
        quantity=1,
        order_type="limit",
        limit_price=limit_price,
    )

    monkeypatch.setattr(
        execution_service,
        "get_session_bar",
        lambda db, order: market_bar,
    )

    result = execution_service.execute_queued_orders(
        db,
        setup["competition"].id,
    )

    executions = get_executions(db)

    assert len(result) == 1
    assert order.status == "filled"
    assert len(executions) == 1
    assert executions[0].execution_price == expected_price
    assert executions[0].slippage == Decimal("0")

    position = db.scalar(
        select(Position).where(
            Position.portfolio_id == portfolio.id,
            Position.stock_id == setup["nvda"].id,
        )
    )

    if side == "buy":
        assert position is not None
        assert position.quantity == position_quantity
    else:
        assert position is not None
        assert position.quantity == position_quantity


def test_unfilled_limit_order_is_rescheduled(
    db,
    trading_setup,
    market_session,
    market_bar,
    monkeypatch,
):
    setup = trading_setup

    order = create_queued_order(
        db,
        setup,
        market_session,
        side="buy",
        quantity=1,
        order_type="limit",
        limit_price=Decimal("90"),
    )

    monkeypatch.setattr(
        execution_service,
        "get_session_bar",
        lambda db, order: market_bar,
    )

    result = execution_service.execute_queued_orders(
        db,
        setup["competition"].id,
    )

    assert len(result) == 1
    assert order.status == "queued"
    assert order.scheduled_execution_at == (
        market_session["next_market_open"].replace(tzinfo=None)
    )
    assert get_executions(db) == []


def test_order_without_market_data_remains_queued(
    db,
    trading_setup,
    market_session,
    monkeypatch,
):
    setup = trading_setup

    order = create_queued_order(
        db,
        setup,
        market_session,
    )

    monkeypatch.setattr(
        execution_service,
        "get_session_bar",
        lambda db, order: None,
    )

    result = execution_service.execute_queued_orders(
        db,
        setup["competition"].id,
    )

    assert result == []
    assert order.status == "queued"
    assert get_executions(db) == []


def test_inactive_competition_cannot_execute_orders(
    db,
    trading_setup,
):
    competition = trading_setup["competition"]
    competition.status = "completed"
    db.commit()

    with pytest.raises(HTTPException) as exc:
        execution_service.execute_queued_orders(
            db,
            competition.id,
        )

    assert exc.value.status_code == 400
    assert get_executions(db) == []

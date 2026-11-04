
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models

from app.api.dependencies import require_api_write_key
from app.core.database import Base
from app.core.config import settings
from app.models import (
    Agent,
    Competition,
    Execution,
    Order,
    Portfolio,
    Position,
    Stock,
    StockBar,
)
from app.schemas.order import OrderCreate
from app.services.brokerage.order_service import (
    get_latest_close,
    submit_order_batch,
)
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app

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

    aapl = Stock(
        symbol="AAPL",
        name="Apple",
        exchange="NASDAQ",
        asset_type="stock",
        is_active=True,
    )

    db.add_all([spy, nvda, aapl])
    db.flush()

    for stock in [nvda, aapl]:
        db.add(
            StockBar(
                stock_id=stock.id,
                timestamp=datetime(2026, 10, 30, tzinfo=timezone.utc),
                timeframe=settings.ALPACA_TIMEFRAME,
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("95"),
                close=Decimal("100"),
                volume=100000,
                provider=settings.ALPACA_PROVIDER,
                feed=settings.ALPACA_FEED,
                adjustment=settings.ALPACA_ADJUSTMENT,
            )
        )

    competition = Competition(
        name="Order Service Test",
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
        "aapl": aapl,
    }


def make_order(symbol, side="buy", quantity=1, order_type="market", limit_price=None):
    return OrderCreate(
        stock_symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
    )


def order_count(db):
    return db.scalar(select(func.count()).select_from(Order))


def test_batch_submits_multiple_buy_orders(db, trading_setup):
    setup = trading_setup

    orders = [
        make_order("NVDA", quantity=2),
        make_order("AAPL", quantity=3),
    ]

    result = submit_order_batch(
        db=db,
        competition_id=setup["competition"].id,
        agent_id=setup["agent"].id,
        orders=orders,
    )

    assert len(result) == 2
    assert {order.side for order in result} == {"buy"}
    assert {order.status for order in result} == {"pending"}
    assert order_count(db) == 2


def test_batch_rejects_insufficient_combined_buying_power(db, trading_setup):
    setup = trading_setup
    setup["portfolio"].cash_balance = Decimal("200")
    db.commit()

    orders = [
        make_order("NVDA", quantity=1),
        make_order("AAPL", quantity=1),
    ]

    with pytest.raises(HTTPException) as exc:
        submit_order_batch(
            db=db,
            competition_id=setup["competition"].id,
            agent_id=setup["agent"].id,
            orders=orders,
        )

    assert exc.value.status_code == 400
    assert order_count(db) == 0


def test_batch_rejects_unknown_stock_without_partial_orders(db, trading_setup):
    setup = trading_setup

    orders = [
        make_order("NVDA"),
        make_order("UNKNOWN"),
    ]

    with pytest.raises(HTTPException) as exc:
        submit_order_batch(
            db=db,
            competition_id=setup["competition"].id,
            agent_id=setup["agent"].id,
            orders=orders,
        )

    assert exc.value.status_code == 404
    assert order_count(db) == 0


def test_batch_rejects_sell_quantity_above_position(db, trading_setup):
    setup = trading_setup

    db.add(
        Position(
            portfolio_id=setup["portfolio"].id,
            stock_id=setup["nvda"].id,
            quantity=5,
            average_entry_price=Decimal("100"),
        )
    )
    db.commit()

    orders = [
        make_order("NVDA", side="sell", quantity=6),
    ]

    with pytest.raises(HTTPException) as exc:
        submit_order_batch(
            db=db,
            competition_id=setup["competition"].id,
            agent_id=setup["agent"].id,
            orders=orders,
        )

    assert exc.value.status_code == 400
    assert order_count(db) == 0


def test_batch_rejects_duplicate_symbols_at_service_level(db, trading_setup):
    setup = trading_setup

    orders = [
        make_order("NVDA", side="sell", quantity=1),
        make_order("NVDA", side="sell", quantity=1),
    ]

    with pytest.raises(HTTPException) as exc:
        submit_order_batch(
            db=db,
            competition_id=setup["competition"].id,
            agent_id=setup["agent"].id,
            orders=orders,
        )

    assert exc.value.status_code == 400
    assert order_count(db) == 0


def test_batch_does_not_use_sell_proceeds_to_fund_buys(db, trading_setup):
    setup = trading_setup
    setup["portfolio"].cash_balance = Decimal("100")

    db.add(
        Position(
            portfolio_id=setup["portfolio"].id,
            stock_id=setup["nvda"].id,
            quantity=10,
            average_entry_price=Decimal("100"),
        )
    )
    db.commit()

    orders = [
        make_order("NVDA", side="sell", quantity=10),
        make_order("AAPL", side="buy", quantity=1),
    ]

    with pytest.raises(HTTPException) as exc:
        submit_order_batch(
            db=db,
            competition_id=setup["competition"].id,
            agent_id=setup["agent"].id,
            orders=orders,
        )

    assert exc.value.status_code == 400
    assert order_count(db) == 0


def test_batch_respects_existing_reserved_buy_orders(db, trading_setup):
    setup = trading_setup
    setup["portfolio"].cash_balance = Decimal("200")

    # Existing partially filled BUY order:
    # Original quantity: 2
    # Already executed: 1
    # Remaining quantity: 1
    existing_order = Order(
        portfolio_id=setup["portfolio"].id,
        stock_id=setup["nvda"].id,
        side="buy",
        order_type="market",
        quantity=2,
        status="partially_filled",
    )
    db.add(existing_order)
    db.flush()

    db.add(
        Execution(
            order_id=existing_order.id,
            quantity=1,
            execution_price=Decimal("100"),
            fees=Decimal("0"),
            slippage=Decimal("0"),
            executed_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
        )
    )
    db.commit()

    # Existing reservation: 1 × $100 × 1.05 = $105
    # New reservation:      1 × $100 × 1.05 = $105
    # Total: $210, exceeding $200 cash.
    orders = [
        make_order("AAPL", side="buy", quantity=1),
    ]

    with pytest.raises(HTTPException) as exc:
        submit_order_batch(
            db=db,
            competition_id=setup["competition"].id,
            agent_id=setup["agent"].id,
            orders=orders,
        )

    assert exc.value.status_code == 400
    assert order_count(db) == 1


def test_batch_respects_existing_reserved_sell_orders(db, trading_setup):
    setup = trading_setup

    db.add(
        Position(
            portfolio_id=setup["portfolio"].id,
            stock_id=setup["nvda"].id,
            quantity=5,
            average_entry_price=Decimal("100"),
        )
    )

    # Existing partially filled SELL order:
    # Original quantity: 4
    # Already executed: 1
    # Remaining quantity: 3
    existing_order = Order(
        portfolio_id=setup["portfolio"].id,
        stock_id=setup["nvda"].id,
        side="sell",
        order_type="market",
        quantity=4,
        status="partially_filled",
    )
    db.add(existing_order)
    db.flush()

    db.add(
        Execution(
            order_id=existing_order.id,
            quantity=1,
            execution_price=Decimal("100"),
            fees=Decimal("0"),
            slippage=Decimal("0"),
            executed_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
        )
    )
    db.commit()

    # Position: 5 shares
    # Already reserved for existing SELL: 3 shares
    # Available: 2 shares
    # Requested: 3 shares
    orders = [
        make_order("NVDA", side="sell", quantity=3),
    ]

    with pytest.raises(HTTPException) as exc:
        submit_order_batch(
            db=db,
            competition_id=setup["competition"].id,
            agent_id=setup["agent"].id,
            orders=orders,
        )

    assert exc.value.status_code == 400
    assert order_count(db) == 1

def test_batch_order_api_returns_created_orders(db, trading_setup):
    setup = trading_setup

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_api_write_key] = lambda: None

    try:
        client = TestClient(app)

        response = client.post(
            f"/api/competitions/{setup['competition'].id}"
            f"/agents/{setup['agent'].id}/orders/batch",
            json={
                "orders": [
                    {
                        "stock_symbol": "NVDA",
                        "side": "buy",
                        "order_type": "market",
                        "quantity": 2,
                    },
                    {
                        "stock_symbol": "AAPL",
                        "side": "buy",
                        "order_type": "limit",
                        "quantity": 3,
                        "limit_price": "95.00",
                    },
                ]
            },
        )

        assert response.status_code == 201

        result = response.json()

        assert len(result) == 2

        assert result[0]["side"] == "buy"
        assert result[0]["order_type"] == "market"
        assert result[0]["quantity"] == 2
        assert result[0]["status"] == "pending"

        assert result[1]["side"] == "buy"
        assert result[1]["order_type"] == "limit"
        assert result[1]["quantity"] == 3
        assert Decimal(result[1]["limit_price"]) == Decimal("95.00")
        assert result[1]["status"] == "pending"

        assert all("id" in order for order in result)
        assert all("portfolio_id" in order for order in result)
        assert all("stock_id" in order for order in result)
        assert all("submitted_at" in order for order in result)

        assert order_count(db) == 2

    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_api_write_key, None)


def test_historical_market_order_price_does_not_use_future_bars(
    db,
    trading_setup,
):
    stock = trading_setup["nvda"]
    db.add_all([
        StockBar(
            stock_id=stock.id,
            timestamp=datetime(2026, 10, 30, 20, tzinfo=timezone.utc),
            timeframe="1Day",
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            provider="alpaca",
            feed="iex",
            adjustment="raw",
        ),
        StockBar(
            stock_id=stock.id,
            timestamp=datetime(2026, 11, 2, 20, tzinfo=timezone.utc),
            timeframe="1Day",
            open=Decimal("200"),
            high=Decimal("200"),
            low=Decimal("200"),
            close=Decimal("200"),
            volume=100,
            provider="alpaca",
            feed="iex",
            adjustment="raw",
        ),
    ])
    db.commit()

    assert get_latest_close(
        db,
        stock.id,
        as_of_date=date(2026, 10, 30),
    ) == Decimal("100")
    assert get_latest_close(db, stock.id) == Decimal("200")

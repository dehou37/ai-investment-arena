from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.database import Base
from app.models import Stock, StockBar
from app.services.brokerage import portfolio_service


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def configured_source(monkeypatch):
    monkeypatch.setattr(
        portfolio_service,
        "settings",
        SimpleNamespace(
            ALPACA_TIMEFRAME="1Day",
            ALPACA_PROVIDER="alpaca",
            ALPACA_FEED="iex",
            ALPACA_ADJUSTMENT="raw",
        ),
    )


def add_bar(db, stock_id, *, provider, feed, close, timestamp):
    bar = StockBar(
        stock_id=stock_id,
        timestamp=timestamp,
        timeframe="1Day",
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=100,
        provider=provider,
        feed=feed,
        adjustment="raw",
    )
    db.add(bar)
    db.flush()
    return bar


def test_latest_portfolio_price_uses_configured_feed_only(
    db,
    configured_source,
):
    stock = Stock(
        symbol="NVDA",
        name="NVIDIA",
        exchange="NASDAQ",
        asset_type="stock",
        is_active=True,
    )
    db.add(stock)
    db.flush()

    timestamp = datetime(2026, 10, 30, 20, tzinfo=timezone.utc)
    add_bar(
        db,
        stock.id,
        provider="alpaca",
        feed="iex",
        close="100",
        timestamp=timestamp,
    )
    add_bar(
        db,
        stock.id,
        provider="fmp",
        feed="delayed",
        close="200",
        timestamp=timestamp,
    )
    db.commit()

    result = portfolio_service.get_latest_raw_close(db, stock.id)

    assert result is not None
    assert result.provider == "alpaca"
    assert result.feed == "iex"
    assert result.close == Decimal("100")


def test_exact_session_price_does_not_fall_back_to_another_provider(
    db,
    configured_source,
):
    stock = Stock(
        symbol="NVDA",
        name="NVIDIA",
        exchange="NASDAQ",
        asset_type="stock",
        is_active=True,
    )
    db.add(stock)
    db.flush()
    add_bar(
        db,
        stock.id,
        provider="fmp",
        feed="delayed",
        close="200",
        timestamp=datetime(2026, 10, 30, 20, tzinfo=timezone.utc),
    )
    db.commit()

    result = portfolio_service.get_raw_close_for_session(
        db,
        stock.id,
        session_date=datetime(2026, 10, 30).date(),
    )

    assert result is None

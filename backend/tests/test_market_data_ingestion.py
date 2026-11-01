
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.services.market_data.ingestion_service import (
    _build_bar_row,
    persist_alpaca_bars,
)


@pytest.fixture
def stock():
    return SimpleNamespace(
        id=uuid4(),
        symbol="NVDA",
    )


@pytest.fixture
def valid_bar():
    return {
        "t": "2026-10-30T04:00:00Z",
        "o": 208.70,
        "h": 209.06,
        "l": 200.95,
        "c": 204.76,
        "v": 4650693,
        "n": 12345,
        "vw": 204.50,
    }


def test_build_bar_row_converts_values_correctly(stock, valid_bar):
    row = _build_bar_row(stock, valid_bar)

    assert row["stock_id"] == stock.id
    assert row["timestamp"] == datetime(
        2026, 10, 30, 4, 0, tzinfo=timezone.utc
    )

    assert row["open"] == Decimal("208.7")
    assert row["high"] == Decimal("209.06")
    assert row["low"] == Decimal("200.95")
    assert row["close"] == Decimal("204.76")

    assert row["volume"] == 4650693
    assert row["trade_count"] == 12345
    assert row["vwap"] == Decimal("204.5")


def test_build_bar_row_rejects_inconsistent_high(stock, valid_bar):
    valid_bar["h"] = 200.0

    with pytest.raises(ValueError, match="high price is inconsistent"):
        _build_bar_row(stock, valid_bar)


def test_build_bar_row_rejects_inconsistent_low(stock, valid_bar):
    valid_bar["h"] = 220.0
    valid_bar["l"] = 210.0

    with pytest.raises(ValueError, match="low price is inconsistent"):
        _build_bar_row(stock, valid_bar)


def test_build_bar_row_rejects_negative_volume(stock, valid_bar):
    valid_bar["v"] = -100

    with pytest.raises(ValueError, match="volume cannot be negative"):
        _build_bar_row(stock, valid_bar)


def test_build_bar_row_rejects_timezone_naive_timestamp(stock, valid_bar):
    valid_bar["t"] = "2026-10-30T04:00:00"

    with pytest.raises(ValueError, match="must include a timezone"):
        _build_bar_row(stock, valid_bar)


def test_build_bar_row_rejects_nonpositive_prices(stock, valid_bar):
    valid_bar["c"] = 0

    with pytest.raises(ValueError, match="OHLC prices must be positive"):
        _build_bar_row(stock, valid_bar)


def test_persist_alpaca_bars_executes_upsert(stock, valid_bar):
    class FakeDatabase:
        def __init__(self):
            self.statement = None
            self.flushed = False

        def execute(self, statement):
            self.statement = statement

        def flush(self):
            self.flushed = True

    db = FakeDatabase()

    result = persist_alpaca_bars(
        db=db,
        stocks_by_symbol={"NVDA": stock},
        bars_by_symbol={"NVDA": [valid_bar]},
    )

    assert result == {
        "symbols_processed": 1,
        "bars_received": 1,
        "bars_upserted": 1,
    }

    assert db.statement is not None
    assert db.flushed is True

    compiled = db.statement.compile(
        dialect=postgresql.dialect()
    )

    assert "ON CONFLICT" in str(compiled).upper()
    assert "DO UPDATE" in str(compiled).upper()


def test_persist_alpaca_bars_handles_empty_response(stock):
    class FakeDatabase:
        def execute(self, statement):
            raise AssertionError("No database write expected.")

        def flush(self):
            raise AssertionError("No flush expected.")

    result = persist_alpaca_bars(
        db=FakeDatabase(),
        stocks_by_symbol={"NVDA": stock},
        bars_by_symbol={"NVDA": []},
    )

    assert result == {
        "symbols_processed": 1,
        "bars_received": 0,
        "bars_upserted": 0,
    }


def test_persist_alpaca_bars_rejects_invalid_data(stock, valid_bar):
    class FakeDatabase:
        def execute(self, statement):
            raise AssertionError("Invalid data must not be persisted.")

        def flush(self):
            raise AssertionError("Invalid data must not be flushed.")

    valid_bar["v"] = -1

    with pytest.raises(ValueError, match="volume cannot be negative"):
        persist_alpaca_bars(
            db=FakeDatabase(),
            stocks_by_symbol={"NVDA": stock},
            bars_by_symbol={"NVDA": [valid_bar]},
        )

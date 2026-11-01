
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.stock import Stock
from app.models.stock_bar import StockBar


def _to_decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Invalid {field_name}: {value!r}")

    if not result.is_finite():
        raise ValueError(f"Non-finite {field_name}: {value!r}")

    return result


def _parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        raise ValueError(f"Invalid bar timestamp: {value!r}")

    if timestamp.tzinfo is None:
        raise ValueError(
            f"Bar timestamp must include a timezone: {value!r}"
        )

    return timestamp


def _build_bar_row(
    stock: Stock,
    bar: dict[str, Any],
) -> dict[str, Any]:
    open_price = _to_decimal(bar.get("o"), "open")
    high_price = _to_decimal(bar.get("h"), "high")
    low_price = _to_decimal(bar.get("l"), "low")
    close_price = _to_decimal(bar.get("c"), "close")

    if min(open_price, high_price, low_price, close_price) <= 0:
        raise ValueError(
            f"{stock.symbol}: OHLC prices must be positive."
        )

    if high_price < max(open_price, close_price, low_price):
        raise ValueError(
            f"{stock.symbol}: high price is inconsistent."
        )

    if low_price > min(open_price, close_price, high_price):
        raise ValueError(
            f"{stock.symbol}: low price is inconsistent."
        )

    try:
        volume = int(bar["v"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{stock.symbol}: invalid volume.")

    if volume < 0:
        raise ValueError(
            f"{stock.symbol}: volume cannot be negative."
        )

    trade_count = bar.get("n")
    if trade_count is not None:
        try:
            trade_count = int(trade_count)
        except (TypeError, ValueError):
            raise ValueError(
                f"{stock.symbol}: invalid trade count."
            )

        if trade_count < 0:
            raise ValueError(
                f"{stock.symbol}: trade count cannot be negative."
            )

    vwap = bar.get("vw")
    if vwap is not None:
        vwap = _to_decimal(vwap, "VWAP")

        if vwap <= 0:
            raise ValueError(
                f"{stock.symbol}: VWAP must be positive."
            )

    return {
        "stock_id": stock.id,
        "timestamp": _parse_timestamp(bar["t"]),
        "timeframe": settings.ALPACA_TIMEFRAME,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "trade_count": trade_count,
        "vwap": vwap,
        "provider": settings.ALPACA_PROVIDER,
        "feed": settings.ALPACA_FEED,
        "adjustment": settings.ALPACA_ADJUSTMENT,
    }


def persist_alpaca_bars(
    db: Session,
    stocks_by_symbol: dict[str, Stock],
    bars_by_symbol: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    """
    Validate and upsert Alpaca bars.

    The caller owns the database transaction and is responsible
    for committing or rolling it back.
    """
    rows_by_key: dict[tuple, dict[str, Any]] = {}
    received_counts: dict[str, int] = {}

    for symbol, stock in stocks_by_symbol.items():
        bars = bars_by_symbol.get(symbol, [])
        received_counts[symbol] = len(bars)

        for bar in bars:
            row = _build_bar_row(stock, bar)
            key = (row["stock_id"], row["timestamp"])

            # Keep the last occurrence if the provider returns
            # duplicate timestamps in the same response.
            rows_by_key[key] = row

    rows = list(rows_by_key.values())

    if not rows:
        return {
            "symbols_processed": len(stocks_by_symbol),
            "bars_received": sum(received_counts.values()),
            "bars_upserted": 0,
        }

    statement = insert(StockBar).values(rows)

    statement = statement.on_conflict_do_update(
        constraint="uq_stock_bar_source",
        set_={
            "open": statement.excluded.open,
            "high": statement.excluded.high,
            "low": statement.excluded.low,
            "close": statement.excluded.close,
            "volume": statement.excluded.volume,
            "trade_count": statement.excluded.trade_count,
            "vwap": statement.excluded.vwap,
        },
    )

    db.execute(statement)
    db.flush()

    return {
        "symbols_processed": len(stocks_by_symbol),
        "bars_received": sum(received_counts.values()),
        "bars_upserted": len(rows),
    }


from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.core.config import settings
from app.models import (
    Competition,
    Stock,
    StockBar,
    StockUniverseMembership,
    StockUniverseSnapshot,
)
from app.services.market_data.alpaca import AlpacaMarketDataClient


COMPETITION_ID = "b906cde8-9c33-41f0-aa1c-2ef571ebabde"

START_DATE = "2026-07-01"
END_DATE = "2026-11-01"

MINIMUM_BARS_PER_SYMBOL = 60


def to_decimal(value):
    return Decimal(str(value)) if value is not None else None


def get_import_symbols():
    """Get Season 2's 30-stock universe plus SPY."""

    with SessionLocal() as db:
        competition = db.get(Competition, COMPETITION_ID)

        if competition is None:
            raise ValueError("Season 2 competition was not found.")

        if competition.status != "pending":
            raise ValueError(
                "Historical import is intended to run before Season 2 starts."
            )

        snapshot = db.scalar(
            select(StockUniverseSnapshot)
            .where(
                StockUniverseSnapshot.status == "completed",
                StockUniverseSnapshot.as_of <= competition.created_at,
            )
            .order_by(StockUniverseSnapshot.as_of.desc())
            .limit(1)
        )

        if snapshot is None:
            raise ValueError(
                "No completed universe snapshot exists before Season 2."
            )

        memberships = db.scalars(
            select(StockUniverseMembership).where(
                StockUniverseMembership.snapshot_id == snapshot.id
            )
        ).all()

        stock_ids = [membership.stock_id for membership in memberships]

        universe_stocks = db.scalars(
            select(Stock).where(
                Stock.id.in_(stock_ids),
                Stock.is_active.is_(True),
                Stock.asset_type == "stock",
            )
        ).all()

        spy = db.scalar(
            select(Stock).where(
                Stock.symbol == "SPY",
                Stock.is_active.is_(True),
            )
        )

        if spy is None:
            raise ValueError("Active SPY stock record was not found.")

        if len(universe_stocks) != 30:
            raise ValueError(
                f"Expected 30 active universe stocks, "
                f"found {len(universe_stocks)}."
            )

        symbols = sorted(stock.symbol for stock in universe_stocks)
        symbols.append("SPY")

        if len(symbols) != len(set(symbols)):
            raise ValueError("Duplicate symbols found in import list.")

        print(f"Universe snapshot: {snapshot.id}")
        print(f"Snapshot date: {snapshot.as_of}")
        print(f"Universe stocks: {len(universe_stocks)}")
        print(f"Total symbols including SPY: {len(symbols)}")

        return symbols


def validate_bars(bars_by_symbol, symbols):
    """Ensure every symbol has sufficient historical data."""

    insufficient = []

    for symbol in symbols:
        count = len(bars_by_symbol.get(symbol, []))

        print(f"{symbol}: {count} bars received")

        if count < MINIMUM_BARS_PER_SYMBOL:
            insufficient.append(f"{symbol} ({count})")

    if insufficient:
        raise ValueError(
            "Insufficient historical data for: "
            + ", ".join(insufficient)
            + ". No database changes were made."
        )


def prepare_rows(db, bars_by_symbol):
    """Convert Alpaca bars into StockBar records."""

    symbols = list(bars_by_symbol.keys())

    stocks = db.scalars(
        select(Stock).where(Stock.symbol.in_(symbols))
    ).all()

    stock_ids = {
        stock.symbol: stock.id
        for stock in stocks
    }

    rows = []

    for symbol, bars in bars_by_symbol.items():
        if symbol not in stock_ids:
            raise ValueError(
                f"No Stock database record found for {symbol}."
            )

        stock_id = stock_ids[symbol]

        for bar in bars:
            timestamp = datetime.fromisoformat(
                bar["t"].replace("Z", "+00:00")
            )

            open_price = to_decimal(bar["o"])
            high_price = to_decimal(bar["h"])
            low_price = to_decimal(bar["l"])
            close_price = to_decimal(bar["c"])

            if (
                high_price < max(open_price, close_price, low_price)
                or low_price > min(open_price, close_price, high_price)
                or bar["v"] < 0
            ):
                raise ValueError(
                    f"Invalid market data for {symbol}: {bar}"
                )

            rows.append({
                "stock_id": stock_id,
                "timestamp": timestamp,
                "timeframe": "1Day",
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": int(bar["v"]),
                "trade_count": bar.get("n"),
                "vwap": to_decimal(bar.get("vw")),
                "provider": "alpaca",
                "feed": settings.ALPACA_FEED,
                "adjustment": "raw",
            })

    return rows


def main():
    symbols = get_import_symbols()

    print("\nFetching historical data from Alpaca...")
    print(f"Period: {START_DATE} to {END_DATE}")
    print(f"Feed: {settings.ALPACA_FEED}")

    client = AlpacaMarketDataClient()

    try:
        bars_by_symbol = client.get_daily_bars(
            symbols=symbols,
            start=START_DATE,
            end=END_DATE,
        )
    finally:
        client.close()

    print("\nValidating received data...")
    validate_bars(bars_by_symbol, symbols)

    print("\nPreparing database records...")

    with SessionLocal() as db:
        try:
            rows = prepare_rows(db, bars_by_symbol)

            print(f"Prepared {len(rows)} daily bars.")

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
            db.commit()

        except Exception:
            db.rollback()
            raise

    with SessionLocal() as db:
        for symbol in symbols:
            stock = db.scalar(
                select(Stock).where(Stock.symbol == symbol)
            )

            count = db.scalar(
                select(func.count(StockBar.id)).where(
                    StockBar.stock_id == stock.id,
                    StockBar.timeframe == "1Day",
                    StockBar.provider == "alpaca",
                    StockBar.feed == settings.ALPACA_FEED,
                    StockBar.adjustment == "raw",
                    StockBar.timestamp >= datetime(
                        2026, 7, 1, tzinfo=timezone.utc
                    ),
                    StockBar.timestamp < datetime(
                        2026, 11, 1, tzinfo=timezone.utc
                    ),
                )
            )

            print(f"{symbol}: {count} bars in database")

            if count < MINIMUM_BARS_PER_SYMBOL:
                raise RuntimeError(
                    f"Verification failed for {symbol}: {count} bars."
                )

    print("\nHistorical data import completed successfully.")


if __name__ == "__main__":
    main()

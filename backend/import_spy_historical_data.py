
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.core.config import settings
from app.models import Stock, StockBar
from app.services.market_data.alpaca import AlpacaMarketDataClient


SYMBOL = "SPY"

# Start with sufficient history for benchmark comparisons.
# Alpaca's end date is exclusive.
START_DATE = "2026-01-01"
END_DATE = "2026-11-01"


def to_decimal(value):
    return Decimal(str(value)) if value is not None else None


def main():
    print(f"Fetching historical data for {SYMBOL} from Alpaca...")

    with SessionLocal() as db:
        stock = db.scalar(
            select(Stock).where(Stock.symbol == SYMBOL)
        )

        if stock is None:
            raise ValueError(
                "SPY does not exist in the stocks table. "
                "Import the SPY stock record first."
            )

        stock_id = stock.id

    client = AlpacaMarketDataClient()

    try:
        bars_by_symbol = client.get_daily_bars(
            symbols=[SYMBOL],
            start=START_DATE,
            end=END_DATE,
        )
    finally:
        client.close()

    bars = bars_by_symbol.get(SYMBOL, [])

    print(f"Received {len(bars)} SPY bars from Alpaca.")

    if not bars:
        raise ValueError(
            "Alpaca returned no SPY bars. "
            "Check your API credentials and market data feed."
        )

    rows = []

    for bar in bars:
        timestamp = datetime.fromisoformat(
            bar["t"].replace("Z", "+00:00")
        )

        open_price = to_decimal(bar["o"])
        high_price = to_decimal(bar["h"])
        low_price = to_decimal(bar["l"])
        close_price = to_decimal(bar["c"])
        volume = int(bar["v"])

        if (
            high_price < max(open_price, close_price, low_price)
            or low_price > min(open_price, close_price, high_price)
            or volume < 0
        ):
            raise ValueError(
                f"Invalid market data for {SYMBOL}: {bar}"
            )

        rows.append({
            "stock_id": stock_id,
            "timestamp": timestamp,
            "timeframe": "1Day",
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
            "trade_count": bar.get("n"),
            "vwap": to_decimal(bar.get("vw")),
            "provider": "alpaca",
            "feed": settings.ALPACA_FEED,
            "adjustment": "raw",
        })

    with SessionLocal() as db:
        with db.begin():
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

    print(f"Imported {len(rows)} SPY daily bars.")
    print("SPY historical data import completed successfully.")


if __name__ == "__main__":
    main()


from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.core.config import settings
from app.models import Stock, StockBar
from app.services.market_data.alpaca import AlpacaMarketDataClient


STOCKS = {
    "NVDA": {
        "name": "NVIDIA Corporation",
        "exchange": "NASDAQ",
    },
    "AAPL": {
        "name": "Apple Inc.",
        "exchange": "NASDAQ",
    },
    "MSFT": {
        "name": "Microsoft Corporation",
        "exchange": "NASDAQ",
    },
}


def to_decimal(value):
    return Decimal(str(value)) if value is not None else None


def main():
    symbols = list(STOCKS.keys())

    print("Fetching historical data from Alpaca...")

    client = AlpacaMarketDataClient()

    try:
        bars_by_symbol = client.get_daily_bars(
            symbols=symbols,
            start="2026-10-01",
            end="2026-10-31",
        )
    finally:
        client.close()

    print("Received market data.")

    with SessionLocal() as db:
        with db.begin():

            # 1. Create stock records if they do not exist.
            for symbol, details in STOCKS.items():
                stock = db.scalar(
                    select(Stock).where(Stock.symbol == symbol)
                )

                if stock is None:
                    db.add(
                        Stock(
                            symbol=symbol,
                            name=details["name"],
                            exchange=details["exchange"],
                        )
                    )

            db.flush()

            # 2. Get stock IDs.
            stocks = db.scalars(
                select(Stock).where(Stock.symbol.in_(symbols))
            ).all()

            stock_ids = {
                stock.symbol: stock.id
                for stock in stocks
            }

            # 3. Prepare daily bar records.
            rows = []

            for symbol, bars in bars_by_symbol.items():
                stock_id = stock_ids[symbol]

                for bar in bars:
                    timestamp = datetime.fromisoformat(
                        bar["t"].replace("Z", "+00:00")
                    )

                    open_price = to_decimal(bar["o"])
                    high_price = to_decimal(bar["h"])
                    low_price = to_decimal(bar["l"])
                    close_price = to_decimal(bar["c"])

                    # Basic market data validation.
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

            # 4. Insert or update existing bars.
            if rows:
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

            print(f"Imported {len(rows)} daily bars.")

    print("Historical data import completed successfully.")


if __name__ == "__main__":
    main()

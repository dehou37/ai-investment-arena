
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import (
    Stock,
    StockUniverseSnapshot,
    StockUniverseMembership,
)
from app.services.stock_universe.nasdaq_client import NasdaqClient
from app.services.stock_universe.universe_selector import (
    select_top_companies,
    UniverseSelectionError,
)


SNAPSHOT_SOURCE = "nasdaq_screener"
EXPECTED_COMPANY_COUNT = 30

# SPY is stored separately as a benchmark ETF.
BENCHMARK = {
    "symbol": "SPY",
    "name": "SPDR S&P 500 ETF Trust",
    "exchange": "NYSE Arca",
    "asset_class": "us_equity",
    "asset_type": "etf",
}


def download_stock_listings() -> list[dict]:
    """Download listings from NASDAQ, NYSE and NYSE American."""

    client = NasdaqClient()
    all_stocks = []

    exchanges = ["nasdaq", "nyse", "amex"]

    for exchange in exchanges:
        print(f"Downloading {exchange.upper()}...")

        stocks = client.get_stocks(
            exchange=exchange,
            limit=5000,
            offset=0,
        )

        for stock in stocks:
            stock["exchange_source"] = exchange

        all_stocks.extend(stocks)

        print(f"Retrieved {len(stocks)} listings.")

    print(f"\nTotal raw listings: {len(all_stocks)}")

    return all_stocks


def ensure_benchmark_stock(db) -> Stock:
    """Create or update SPY as a separate ETF record."""

    statement = select(Stock).where(
        Stock.symbol == BENCHMARK["symbol"]
    )

    stock = db.scalar(statement)

    if stock is None:
        stock = Stock(
            symbol=BENCHMARK["symbol"],
            name=BENCHMARK["name"],
            exchange=BENCHMARK["exchange"],
            asset_class=BENCHMARK["asset_class"],
            asset_type=BENCHMARK["asset_type"],
            is_active=True,
        )

        db.add(stock)

    else:
        stock.name = BENCHMARK["name"]
        stock.exchange = BENCHMARK["exchange"]
        stock.asset_class = BENCHMARK["asset_class"]
        stock.asset_type = BENCHMARK["asset_type"]
        stock.is_active = True

    return stock


def create_or_update_stock(db, company: dict) -> Stock:
    """Create a new stock or update an existing stock record."""

    symbol = company["symbol"]

    statement = select(Stock).where(
        Stock.symbol == symbol
    )

    stock = db.scalar(statement)

    market_cap = Decimal(str(company["market_cap"]))

    exchange = str(
        company.get("exchange_source", "")
    ).upper()

    if stock is None:
        stock = Stock(
            symbol=symbol,
            name=company["name"],
            exchange=exchange,
            asset_class="us_equity",
            asset_type="stock",
            sector="Technology",
            industry=company["industry"],
            market_cap=market_cap,
            is_active=True,
        )

        db.add(stock)

    else:
        stock.name = company["name"]
        stock.exchange = exchange
        stock.asset_class = "us_equity"
        stock.asset_type = "stock"
        stock.sector = "Technology"
        stock.industry = company["industry"]
        stock.market_cap = market_cap
        stock.is_active = True

    return stock


def import_stock_universe():
    """Import the top 30 technology companies as a new snapshot."""

    print("=" * 70)
    print("AI INVESTMENT ARENA - STOCK UNIVERSE IMPORT")
    print("=" * 70)

    # ---------------------------------------------------------
    # 1. Download exchange listings
    # ---------------------------------------------------------

    try:
        all_stocks = download_stock_listings()

    except Exception as error:
        print(f"\nERROR downloading stock listings: {error}")
        return

    # ---------------------------------------------------------
    # 2. Select the top 30 companies
    # ---------------------------------------------------------

    print("\nSelecting top 30 technology companies...")

    try:
        selected = select_top_companies(
            rows=all_stocks,
            limit=EXPECTED_COMPANY_COUNT,
        )

    except UniverseSelectionError as error:
        print(f"\nUNIVERSE SELECTION FAILED: {error}")
        return

    if len(selected) != EXPECTED_COMPANY_COUNT:
        print(
            f"\nERROR: Expected {EXPECTED_COMPANY_COUNT} companies, "
            f"received {len(selected)}."
        )
        return

    print(f"Selected {len(selected)} companies.")

    # ---------------------------------------------------------
    # 3. Validate mandatory companies
    # ---------------------------------------------------------

    selected_symbols = {
        company["issuer_symbol"]
        for company in selected
    }

    mandatory_symbols = {
        "INTC",
        "GOOGL",
        "AMZN",
        "META",
    }

    missing_symbols = mandatory_symbols - selected_symbols

    if missing_symbols:
        print(
            "\nERROR: Mandatory companies missing: "
            + ", ".join(sorted(missing_symbols))
        )
        return

    # ---------------------------------------------------------
    # 4. Begin database transaction
    # ---------------------------------------------------------

    db = SessionLocal()

    try:
        print("\nStarting database transaction...")

        # Create a new snapshot for this import.
        snapshot = StockUniverseSnapshot(
            source=SNAPSHOT_SOURCE,
            status="completed",
            as_of=datetime.now(timezone.utc),
            total_members=len(selected),
        )

        db.add(snapshot)
        db.flush()

        print(f"Created snapshot: {snapshot.id}")

        # -----------------------------------------------------
        # 5. Create or update stock records and memberships
        # -----------------------------------------------------

        for company in selected:
            stock = create_or_update_stock(db, company)

            # Generate the stock UUID before creating membership.
            db.flush()

            membership = StockUniverseMembership(
                snapshot_id=snapshot.id,
                stock_id=stock.id,
                sector="Technology",
                industry=company["industry"],
                market_cap=Decimal(
                    str(company["market_cap"])
                ),
                sector_rank=company["sector_rank"],
            )

            db.add(membership)

            print(
                f"[{company['sector_rank']:02}] "
                f"{company['symbol']:<8} "
                f"${company['market_cap']:,.0f}"
            )

        # -----------------------------------------------------
        # 6. Register SPY separately
        # -----------------------------------------------------

        benchmark = ensure_benchmark_stock(db)

        print(
            f"\nBenchmark registered: "
            f"{benchmark.symbol} ({benchmark.asset_type})"
        )

        # -----------------------------------------------------
        # 7. Commit transaction
        # -----------------------------------------------------

        db.commit()

        print("\n" + "=" * 70)
        print("STOCK UNIVERSE IMPORT SUCCESSFUL")
        print("=" * 70)

        print(f"Snapshot ID: {snapshot.id}")
        print(f"Companies imported: {len(selected)}")
        print(f"Benchmark: {benchmark.symbol}")
        print("Sector: Technology")
        print("Status: completed")

    except Exception as error:
        db.rollback()

        print("\n" + "=" * 70)
        print("STOCK UNIVERSE IMPORT FAILED")
        print("=" * 70)

        print(f"Error: {error}")
        print("Database transaction rolled back.")
        print("No partial snapshot was saved.")

        raise

    finally:
        db.close()


if __name__ == "__main__":
    import_stock_universe()

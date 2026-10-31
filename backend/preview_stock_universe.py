
from app.services.stock_universe.nasdaq_client import NasdaqClient
from app.services.stock_universe.universe_selector import (
    select_top_companies,
    UniverseSelectionError,
)


def main():
    client = NasdaqClient()

    all_stocks = []

    # ---------------------------------------------------------
    # 1. Download listings from all supported US exchanges
    # ---------------------------------------------------------

    exchanges = ["nasdaq", "nyse", "amex"]

    for exchange in exchanges:
        print(f"Downloading {exchange.upper()}...")

        try:
            stocks = client.get_stocks(
                exchange=exchange,
                limit=5000,
                offset=0,
            )

            # Keep track of the exchange each listing came from.
            for stock in stocks:
                stock["exchange_source"] = exchange

            all_stocks.extend(stocks)

            print(f"Retrieved {len(stocks)} listings.")

        except Exception as error:
            print(f"ERROR downloading {exchange.upper()}: {error}")
            raise

    print(f"\nTotal raw listings: {len(all_stocks)}")

    # ---------------------------------------------------------
    # 2. Select the top 30 broad technology companies
    # ---------------------------------------------------------

    print("\nSelecting top 30 technology companies...")

    try:
        selected = select_top_companies(
            rows=all_stocks,
            limit=30,
        )

    except UniverseSelectionError as error:
        print(f"\nUNIVERSE SELECTION FAILED: {error}")
        return

    # ---------------------------------------------------------
    # 3. Display selected companies
    # ---------------------------------------------------------

    print("\n" + "=" * 110)
    print("TOP 30 BROAD TECHNOLOGY STOCK UNIVERSE")
    print("=" * 110)

    print(
        f"{'Rank':<6}"
        f"{'Symbol':<10}"
        f"{'Company':<40}"
        f"{'Market Cap (USD)':>25}    "
        f"{'Industry'}"
    )

    print("-" * 110)

    for company in selected:
        rank = company["sector_rank"]
        symbol = company["symbol"]
        name = company["name"]
        market_cap = company["market_cap"]
        industry = company["industry"]

        print(
            f"{rank:<6}"
            f"{symbol:<10}"
            f"{name[:38]:<40}"
            f"${market_cap:>24,.0f}    "
            f"{industry}"
        )

    print("-" * 110)

    # ---------------------------------------------------------
    # 4. Summary
    # ---------------------------------------------------------

    print(f"\nTOTAL SELECTED: {len(selected)}")

    unique_symbols = {
        company["issuer_symbol"]
        for company in selected
    }

    print(f"UNIQUE COMPANIES: {len(unique_symbols)}")

    # ---------------------------------------------------------
    # 5. Mandatory company checks
    # ---------------------------------------------------------

    print("\nMANDATORY COMPANY CHECKS")
    print("-" * 40)

    mandatory_symbols = [
        "INTC",
        "GOOGL",
        "AMZN",
        "META",
    ]

    for symbol in mandatory_symbols:
        found = any(
            company["issuer_symbol"] == symbol
            for company in selected
        )

        status = "FOUND" if found else "MISSING"

        print(f"{symbol:<10} {status}")

    # ---------------------------------------------------------
    # 6. Exchange distribution
    # ---------------------------------------------------------

    print("\nEXCHANGE DISTRIBUTION")
    print("-" * 40)

    exchange_counts = {}

    for company in selected:
        exchange = company.get("exchange_source", "unknown").upper()

        exchange_counts[exchange] = (
            exchange_counts.get(exchange, 0) + 1
        )

    for exchange, count in sorted(exchange_counts.items()):
        print(f"{exchange:<10} {count}")

    # ---------------------------------------------------------
    # 7. Final validation
    # ---------------------------------------------------------

    print("\nFINAL VALIDATION")
    print("-" * 40)

    checks = {
        "Exactly 30 companies": len(selected) == 30,
        "30 unique companies": len(unique_symbols) == 30,
        "Intel included": "INTC" in unique_symbols,
        "Alphabet included": "GOOGL" in unique_symbols,
        "Amazon included": "AMZN" in unique_symbols,
        "Meta included": "META" in unique_symbols,
        "All companies have positive market cap": all(
            company["market_cap"] > 0
            for company in selected
        ),
    }

    for description, passed in checks.items():
        print(
            f"{'[PASS]' if passed else '[FAIL]'} "
            f"{description}"
        )

    if all(checks.values()):
        print("\nPreview completed successfully.")
        print("No database records have been modified.")
    else:
        print("\nPreview completed with validation failures.")
        print("Review the results before importing.")


if __name__ == "__main__":
    main()

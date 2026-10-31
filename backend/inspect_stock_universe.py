
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from app.services.stock_universe.nasdaq_client import (
    NasdaqClient,
    NasdaqClientError,
)


def parse_market_cap(value):
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def main():
    client = NasdaqClient()

    all_stocks = []
    country_counts = Counter()
    sector_counts = Counter()
    valid_sector_counts = Counter()
    sector_examples = defaultdict(list)

    for exchange in client.EXCHANGES:
        print(f"Downloading {exchange.upper()} listings...")

        try:
            stocks = client.get_stocks(
                exchange=exchange,
                limit=5000,
            )

            print(f"Retrieved {len(stocks)} listings.")

            for stock in stocks:
                stock["exchange_source"] = exchange.upper()
                all_stocks.append(stock)

        except NasdaqClientError as exc:
            print(f"ERROR: {exc}")
            return

    print(f"\nTotal retrieved listings: {len(all_stocks)}")

    unique_symbols = {
        stock.get("symbol")
        for stock in all_stocks
        if stock.get("symbol")
    }

    print(f"Unique symbols: {len(unique_symbols)}")

    for stock in all_stocks:
        country = (stock.get("country") or "UNKNOWN").strip()
        sector = (stock.get("sector") or "UNKNOWN").strip()

        market_cap = parse_market_cap(stock.get("marketCap"))

        country_counts[country] += 1
        sector_counts[sector] += 1

        if market_cap > 0 and sector != "UNKNOWN":
            valid_sector_counts[sector] += 1

            if len(sector_examples[sector]) < 3:
                sector_examples[sector].append(
                    (
                        stock.get("symbol"),
                        stock.get("name"),
                        market_cap,
                        country,
                    )
                )

    print("\n========== SECTOR DISTRIBUTION ==========")

    for sector, count in sector_counts.most_common():
        valid_count = valid_sector_counts[sector]

        print(
            f"{sector}: {count} listings "
            f"({valid_count} with positive market cap)"
        )

        for symbol, name, market_cap, country in sector_examples[sector]:
            print(
                f"    {symbol} | {name} | "
                f"Market cap: {market_cap:,.0f} | Country: {country}"
            )

    print("\n========== COUNTRY DISTRIBUTION ==========")

    for country, count in country_counts.most_common(20):
        print(f"{country}: {count}")

    print("\n========== DATA QUALITY ==========")

    zero_market_cap = sum(
        1
        for stock in all_stocks
        if parse_market_cap(stock.get("marketCap")) <= 0
    )

    missing_sector = sum(
        1
        for stock in all_stocks
        if not (stock.get("sector") or "").strip()
    )

    missing_country = sum(
        1
        for stock in all_stocks
        if not (stock.get("country") or "").strip()
    )

    print(f"Zero/invalid market cap: {zero_market_cap}")
    print(f"Missing sector: {missing_sector}")
    print(f"Missing country: {missing_country}")

    print("\nInspection completed.")


if __name__ == "__main__":
    main()

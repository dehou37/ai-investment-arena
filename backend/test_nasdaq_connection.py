
from app.services.stock_universe.nasdaq_client import (
    NasdaqClient,
    NasdaqClientError,
)


def main():
    print("Testing Nasdaq stock screener...")

    client = NasdaqClient()

    for exchange in client.EXCHANGES:
        print(f"\nChecking {exchange.upper()}...")

        try:
            stocks = client.get_stocks(
                exchange=exchange,
                limit=10,
            )

            print(f"Retrieved {len(stocks)} stocks.")

            for stock in stocks[:5]:
                print(
                    f"{stock.get('symbol')} | "
                    f"{stock.get('name')} | "
                    f"Sector: {stock.get('sector')} | "
                    f"Industry: {stock.get('industry')} | "
                    f"Market cap: {stock.get('marketCap')}"
                )

            if stocks:
                print("\nAvailable fields:")
                print(", ".join(stocks[0].keys()))

        except NasdaqClientError as exc:
            print(f"Failed: {exc}")

    print("\nNasdaq test completed.")


if __name__ == "__main__":
    main()

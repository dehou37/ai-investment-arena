from app.services.market_data.alpaca import AlpacaMarketDataClient


def main():
    client = AlpacaMarketDataClient()

    try:
        bars = client.get_daily_bars(
            symbols=["NVDA", "AAPL", "MSFT"],
            start="2026-10-01",
            end="2026-10-30",
        )

        for symbol, daily_bars in bars.items():
            print(f"\n{symbol}")
            print(f"Number of daily bars: {len(daily_bars)}")

            if daily_bars:
                latest = daily_bars[-1]

                print(f"Date:   {latest['t']}")
                print(f"Open:   {latest['o']}")
                print(f"High:   {latest['h']}")
                print(f"Low:    {latest['l']}")
                print(f"Close:  {latest['c']}")
                print(f"Volume: {latest['v']}")

    finally:
        client.close()


if __name__ == "__main__":
    main()
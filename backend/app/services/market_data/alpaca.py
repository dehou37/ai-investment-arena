
import httpx

from app.core.config import settings


class AlpacaMarketDataClient:
    def __init__(self):
        self.client = httpx.Client(
            base_url=settings.ALPACA_DATA_URL,
            headers={
                "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
            },
            timeout=30.0,
        )

    def get_daily_bars(
        self,
        symbols: list[str],
        start: str,
        end: str,
    ) -> dict:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": settings.ALPACA_TIMEFRAME,
            "start": start,
            "end": end,
            "adjustment": settings.ALPACA_ADJUSTMENT,
            "feed": settings.ALPACA_FEED,
            "limit": 10000,
            "sort": "asc",
        }

        all_bars = {symbol: [] for symbol in symbols}

        while True:
            response = self.client.get(
                "/v2/stocks/bars",
                params=params,
            )
            response.raise_for_status()

            data = response.json()

            for symbol, bars in data.get("bars", {}).items():
                all_bars.setdefault(symbol, []).extend(bars)

            next_page_token = data.get("next_page_token")

            if not next_page_token:
                break

            params["page_token"] = next_page_token

        return all_bars

    def close(self):
        self.client.close()

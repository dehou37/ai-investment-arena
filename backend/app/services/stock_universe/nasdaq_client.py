
from typing import Any

import httpx


class NasdaqClientError(Exception):
    """Raised when the Nasdaq screener request fails."""


class NasdaqClient:
    BASE_URL = "https://api.nasdaq.com/api/screener/stocks"
    EXCHANGES = ["nasdaq", "nyse", "amex"]

    def get_stocks(
        self,
        exchange: str,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        exchange = exchange.lower()

        if exchange not in self.EXCHANGES:
            raise ValueError(f"Unsupported exchange: {exchange}")

        params = {
            "tableonly": "false",
            "download": "true",
            "limit": limit,
            "offset": offset,
            "exchange": exchange,
        }

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/market-activity/stocks/screener",
        }

        try:
            with httpx.Client(timeout=45.0) as client:
                response = client.get(
                    self.BASE_URL,
                    params=params,
                    headers=headers,
                )

            response.raise_for_status()
            payload = response.json()

            data = payload.get("data") or {}

            # Nasdaq has returned more than one response structure.
            rows = data.get("rows")

            if rows is None:
                table = data.get("table") or {}
                rows = table.get("rows")

            if not isinstance(rows, list):
                raise NasdaqClientError(
                    f"Unexpected Nasdaq response: {str(payload)[:1000]}"
                )

            return rows

        except httpx.HTTPStatusError as exc:
            raise NasdaqClientError(
                f"Nasdaq HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc

        except httpx.RequestError as exc:
            raise NasdaqClientError(
                f"Could not connect to Nasdaq: {exc}"
            ) from exc

        except ValueError as exc:
            raise NasdaqClientError(
                f"Could not parse Nasdaq response: {exc}"
            ) from exc


from typing import Any

import httpx

from app.core.config import settings


class FMPClientError(Exception):
    """Raised when the Financial Modeling Prep API request fails."""


class FMPClient:
    BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(self) -> None:
        if not settings.FMP_API_KEY:
            raise FMPClientError(
                "FMP_API_KEY is missing. Add it to backend/.env."
            )

        self.api_key = settings.FMP_API_KEY

    def get_company_screener(
        self,
        page: int = 0,
        limit: int = 10,
        sector: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve one page of companies from the FMP stock screener.

        We deliberately retrieve raw provider data here.
        Sector mapping, ranking and stock selection happen
        in the universe service later.
        """

        url = f"{self.BASE_URL}/company-screener"

        params: dict[str, Any] = {
            "apikey": self.api_key,
            "country": "US",
            "exchange": "NASDAQ,NYSE,AMEX",
            "isEtf": "false",
            "isFund": "false",
            "isActivelyTrading": "true",
            "includeAllShareClasses": "false",
            "page": page,
            "limit": limit,
        }

        if sector:
            params["sector"] = sector

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=params)

            if response.status_code in (401, 403, 402):
                raise FMPClientError(
                    "FMP rejected the request. Check your API key "
                    "and whether your plan permits the screener endpoint. "
                    f"HTTP status: {response.status_code}"
                )

            if response.status_code == 429:
                raise FMPClientError(
                    "FMP rate limit reached. Try again later."
                )

            response.raise_for_status()

            data = response.json()

            if isinstance(data, dict):
                error_message = (
                    data.get("Error Message")
                    or data.get("error")
                    or data.get("message")
                )

                if error_message:
                    raise FMPClientError(str(error_message))

                raise FMPClientError(
                    f"Unexpected FMP response: {data}"
                )

            if not isinstance(data, list):
                raise FMPClientError(
                    "FMP returned an unexpected response format."
                )

            return data

        except httpx.TimeoutException as exc:
            raise FMPClientError(
                "FMP request timed out."
            ) from exc

        except httpx.HTTPStatusError as exc:
            raise FMPClientError(
                f"FMP HTTP error: {exc.response.status_code} "
                f"{exc.response.text[:500]}"
            ) from exc

        except httpx.RequestError as exc:
            raise FMPClientError(
                f"Could not connect to FMP: {exc}"
            ) from exc

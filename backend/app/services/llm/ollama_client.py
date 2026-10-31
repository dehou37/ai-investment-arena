
import httpx
from pydantic import BaseModel

from app.core.config import settings


class OllamaClientError(Exception):
    """Raised when communication with Ollama fails."""


class OllamaClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 180.0,
        http_client: httpx.Client | None = None,
    ):
        if timeout_seconds <= 0:
            raise ValueError("Timeout must be greater than zero.")

        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout_seconds = timeout_seconds

        self._owns_http_client = http_client is None
        self._closed = False

        self._http_client = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds)
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        response_schema: type[BaseModel],
    ) -> str:
        """Send a structured chat request to Ollama."""

        if self._closed:
            raise OllamaClientError("Ollama client is closed.")

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": response_schema.model_json_schema(),
            "options": {
                "temperature": 0,
            },
        }

        try:
            response = self._http_client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )

            response.raise_for_status()
            response_data = response.json()

        except httpx.TimeoutException as error:
            raise OllamaClientError(
                f"Ollama request timed out after "
                f"{self.timeout_seconds} seconds."
            ) from error

        except httpx.HTTPStatusError as error:
            raise OllamaClientError(
                f"Ollama returned HTTP {error.response.status_code}."
            ) from error

        except httpx.HTTPError as error:
            raise OllamaClientError(
                f"Could not communicate with Ollama: {error}"
            ) from error

        except ValueError as error:
            raise OllamaClientError(
                "Ollama returned an invalid JSON response."
            ) from error

        try:
            content = response_data["message"]["content"]

        except (KeyError, TypeError) as error:
            raise OllamaClientError(
                "Ollama response did not contain message content."
            ) from error

        if not isinstance(content, str) or not content.strip():
            raise OllamaClientError(
                "Ollama returned an empty response."
            )

        return content

    def close(self) -> None:
        """Close the HTTP client if this instance owns it."""

        if self._closed:
            return

        if self._owns_http_client:
            self._http_client.close()

        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

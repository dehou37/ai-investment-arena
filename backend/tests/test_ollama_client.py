import json

import httpx
import pytest
from pydantic import BaseModel

from app.services.llm.ollama_client import (
    MAX_OUTPUT_TOKENS,
    OllamaClient,
    OllamaClientError,
)


class ResponseSchema(BaseModel):
    message: str


def create_client(handler):
    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
    )
    return (
        OllamaClient(
            base_url="http://ollama",
            model="test-model",
            http_client=http_client,
        ),
        http_client,
    )


def test_chat_sets_an_explicit_output_token_limit():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["options"]["num_predict"] == MAX_OUTPUT_TOKENS
        assert payload["options"]["num_ctx"] == 8192
        return httpx.Response(
            200,
            json={
                "message": {"content": '{"message":"ok"}'},
                "done_reason": "stop",
            },
        )

    client, http_client = create_client(handler)
    try:
        assert client.chat(
            messages=[{"role": "user", "content": "test"}],
            response_schema=ResponseSchema,
        ) == '{"message":"ok"}'
    finally:
        http_client.close()


def test_chat_reports_response_truncated_at_output_token_limit():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "message": {"content": '{"message":"incomplete'},
                "done_reason": "length",
            },
        )

    client, http_client = create_client(handler)
    try:
        with pytest.raises(OllamaClientError, match="truncated"):
            client.chat(
                messages=[{"role": "user", "content": "test"}],
                response_schema=ResponseSchema,
            )
    finally:
        http_client.close()

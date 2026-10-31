
import asyncio

import pytest

from app import main


def test_lifespan_creates_and_closes_shared_ollama_client(
    monkeypatch,
):
    created_clients = []

    class FakeOllamaClient:
        def __init__(self):
            self.closed = False
            created_clients.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        main,
        "OllamaClient",
        FakeOllamaClient,
    )

    async def run_lifespan():
        async with main.lifespan(main.app):
            assert len(created_clients) == 1

            client = created_clients[0]

            assert main.app.state.ollama_client is client

            assert (
                main.app.state.decision_orchestrator.ollama_client
                is client
            )

            assert client.closed is False

    asyncio.run(run_lifespan())

    assert len(created_clients) == 1
    assert created_clients[0].closed is True


def test_lifespan_closes_client_when_application_fails(
    monkeypatch,
):
    created_clients = []

    class FakeOllamaClient:
        def __init__(self):
            self.closed = False
            created_clients.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        main,
        "OllamaClient",
        FakeOllamaClient,
    )

    async def run_lifespan():
        async with main.lifespan(main.app):
            raise RuntimeError("Simulated application failure")

    with pytest.raises(
        RuntimeError,
        match="Simulated application failure",
    ):
        asyncio.run(run_lifespan())

    assert len(created_clients) == 1
    assert created_clients[0].closed is True

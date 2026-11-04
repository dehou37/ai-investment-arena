
import asyncio
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app import main
from app.services.trading import scheduler_service


@contextmanager
def lock_acquired():
    yield True


def test_health_endpoint_is_liveness_only():
    assert asyncio.run(main.health()) == {"status": "healthy"}


def test_readiness_reports_database_health(monkeypatch):
    db = Mock()
    session_context = Mock()
    session_context.__enter__ = Mock(return_value=db)
    session_context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(
        main,
        "SessionLocal",
        Mock(return_value=session_context),
    )

    result = asyncio.run(main.readiness())

    assert result == {
        "status": "ready",
        "dependencies": {"database": "healthy"},
    }
    db.execute.assert_called_once()


def test_readiness_returns_service_unavailable_when_database_fails(
    monkeypatch,
):
    db = Mock()
    db.execute.side_effect = RuntimeError("database is unavailable")
    session_context = Mock()
    session_context.__enter__ = Mock(return_value=db)
    session_context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(
        main,
        "SessionLocal",
        Mock(return_value=session_context),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.readiness())

    assert exc.value.status_code == 503
    assert exc.value.detail["status"] == "not_ready"


class FakeOllamaClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeAlpacaClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeAutonomousTradingService:
    def __init__(self, client, recovery_service):
        self.client = client
        self.recovery_service = recovery_service
        self.run_called = False

    def run_all_active_competitions(self):
        self.run_called = True
        return {
            "total_competitions": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
        }


def configure_lifecycle_mocks(monkeypatch):
    monkeypatch.setattr(
        scheduler_service,
        "acquire_scheduler_lock",
        lock_acquired,
    )
    ollama_clients = []
    alpaca_clients = []
    autonomous_services = []

    def create_ollama_client():
        client = FakeOllamaClient()
        ollama_clients.append(client)
        return client

    def create_alpaca_client():
        client = FakeAlpacaClient()
        alpaca_clients.append(client)
        return client

    original_autonomous_service = FakeAutonomousTradingService

    def create_autonomous_service(client, recovery_service):
        service = original_autonomous_service(
            client=client,
            recovery_service=recovery_service,
        )
        autonomous_services.append(service)
        return service

    monkeypatch.setattr(
        main,
        "OllamaClient",
        create_ollama_client,
    )

    monkeypatch.setattr(
        main,
        "AlpacaMarketDataClient",
        create_alpaca_client,
    )

    monkeypatch.setattr(
        main,
        "AutonomousTradingService",
        create_autonomous_service,
    )

    return ollama_clients, alpaca_clients, autonomous_services


def test_lifespan_creates_and_closes_shared_clients(
    monkeypatch,
):
    ollama_clients, alpaca_clients, autonomous_services = (
        configure_lifecycle_mocks(monkeypatch)
    )

    async def run_lifespan():
        async with main.lifespan(main.app):
            assert len(ollama_clients) == 1
            assert len(alpaca_clients) == 1
            assert len(autonomous_services) == 1

            ollama_client = ollama_clients[0]
            alpaca_client = alpaca_clients[0]
            autonomous_service = autonomous_services[0]

            assert main.app.state.ollama_client is ollama_client
            assert main.app.state.alpaca_client is alpaca_client

            assert (
                main.app.state.decision_orchestrator.ollama_client
                is ollama_client
            )

            assert (
                autonomous_service.client
                is alpaca_client
            )

            assert (
                main.app.state.autonomous_trading_service
                is autonomous_service
            )

            assert (
                main.app.state.daily_trading_scheduler_service
                .autonomous_service
                is autonomous_service
            )

            assert ollama_client.closed is False
            assert alpaca_client.closed is False

            # Startup must use the autonomous workflow.
            assert autonomous_service.run_called is True

    asyncio.run(run_lifespan())

    assert ollama_clients[0].closed is True
    assert alpaca_clients[0].closed is True


def test_lifespan_closes_clients_when_application_fails(
    monkeypatch,
):
    ollama_clients, alpaca_clients, _ = (
        configure_lifecycle_mocks(monkeypatch)
    )

    async def run_lifespan():
        async with main.lifespan(main.app):
            raise RuntimeError("Simulated application failure")

    with pytest.raises(
        RuntimeError,
        match="Simulated application failure",
    ):
        asyncio.run(run_lifespan())

    assert len(ollama_clients) == 1
    assert len(alpaca_clients) == 1

    assert ollama_clients[0].closed is True
    assert alpaca_clients[0].closed is True

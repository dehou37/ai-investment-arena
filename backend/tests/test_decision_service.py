
from datetime import date
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.schemas.agent_decision import AgentDecision
from app.services.trading.decision_service import (
    DecisionOrchestrationError,
    DecisionOrchestrator,
)


@pytest.fixture
def ollama_client():
    return Mock()


@pytest.fixture
def orchestrator(ollama_client):
    return DecisionOrchestrator(ollama_client=ollama_client)


@pytest.fixture
def market_context():
    return {
        "agent": {
            "id": str(uuid4()),
            "name": "Momentum",
            "strategy_type": "momentum",
        }
    }


def test_orchestrator_initializes_with_shared_client(
    ollama_client,
    orchestrator,
):
    assert orchestrator.ollama_client is ollama_client


def test_generate_decision_builds_context_and_returns_decision(
    monkeypatch,
    orchestrator,
    market_context,
):
    from app.services.trading import decision_service

    expected_decision = AgentDecision(
        as_of_date="2026-10-30",
        summary="Momentum conditions are positive.",
        decisions=[],
    )

    context_builder = Mock(return_value=market_context)
    strategy = Mock()
    strategy.generate_decision.return_value = expected_decision

    registry_get = Mock(return_value=strategy)

    monkeypatch.setattr(
        decision_service,
        "build_agent_market_context",
        context_builder,
    )
    monkeypatch.setattr(
        decision_service.StrategyRegistry,
        "get",
        registry_get,
    )

    competition_id = uuid4()
    agent_id = uuid4()
    db = Mock()
    as_of_date = date(2026, 10, 30)

    result = orchestrator.generate_agent_decision(
        db=db,
        competition_id=competition_id,
        agent_id=agent_id,
        as_of_date=as_of_date,
    )

    assert result == expected_decision

    context_builder.assert_called_once_with(
        db=db,
        competition_id=competition_id,
        agent_id=agent_id,
        as_of_date=as_of_date,
    )

    registry_get.assert_called_once_with("momentum")
    strategy.generate_decision.assert_called_once_with(market_context)


def test_llm_analyst_receives_shared_ollama_client(
    monkeypatch,
    orchestrator,
    ollama_client,
):
    from app.services.trading import decision_service

    context = {
        "agent": {
            "strategy_type": "llm_analyst",
        }
    }

    expected_decision = AgentDecision(
        as_of_date="2026-10-30",
        summary="AI Analyst recommends holding.",
        decisions=[],
    )

    monkeypatch.setattr(
        decision_service,
        "build_agent_market_context",
        Mock(return_value=context),
    )

    strategy = Mock()
    strategy.generate_decision.return_value = expected_decision

    registry_get = Mock(return_value=strategy)

    monkeypatch.setattr(
        decision_service.StrategyRegistry,
        "get",
        registry_get,
    )

    result = orchestrator.generate_agent_decision(
        db=Mock(),
        competition_id=uuid4(),
        agent_id=uuid4(),
        as_of_date=date(2026, 10, 30),
    )

    assert result == expected_decision

    registry_get.assert_called_once_with(
        "llm_analyst",
        ollama_client=ollama_client,
    )


def test_context_builder_failure_is_wrapped(
    monkeypatch,
    orchestrator,
):
    from app.services.trading import decision_service

    monkeypatch.setattr(
        decision_service,
        "build_agent_market_context",
        Mock(side_effect=ValueError("Competition not found.")),
    )

    with pytest.raises(
        DecisionOrchestrationError,
        match="Competition not found",
    ):
        orchestrator.generate_agent_decision(
            db=Mock(),
            competition_id=uuid4(),
            agent_id=uuid4(),
            as_of_date=date(2026, 10, 30),
        )

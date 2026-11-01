
from datetime import date
from unittest.mock import Mock
from uuid import uuid4
from fastapi import HTTPException
import pytest

from app.schemas.agent_decision import (
    AgentDecision,
    AgentTradeDecision,
)
from app.services.trading.decision_service import (
    DecisionOrchestrationError,
    DecisionOrchestrator,
)
from app.services.trading.risk_service import RiskValidationError


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
        },
        "as_of_date": "2026-10-30",
        "portfolio": {
            "cash_balance": "10000",
            "holdings": [],
        },
        "universe": {
            "stocks": [],
        },
        "trading_constraints": {
            "long_only": True,
            "whole_shares_only": True,
            "fractional_shares_allowed": False,
            "margin_allowed": False,
            "short_selling_allowed": False,
        },
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
    market_context,
):
    from app.services.trading import decision_service

    context = {
        **market_context,
        "agent": {
            "strategy_type": "llm_analyst",
        },
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


def test_risk_validation_failure_rejects_decision(
    monkeypatch,
    orchestrator,
    market_context,
):
    from app.services.trading import decision_service

    expected_decision = AgentDecision(
        as_of_date="2026-10-30",
        summary="Unsafe trading decision.",
        decisions=[],
    )

    strategy = Mock()
    strategy.generate_decision.return_value = expected_decision

    monkeypatch.setattr(
        decision_service,
        "build_agent_market_context",
        Mock(return_value=market_context),
    )

    monkeypatch.setattr(
        decision_service.StrategyRegistry,
        "get",
        Mock(return_value=strategy),
    )

    validator = Mock(
        side_effect=RiskValidationError(
            "Total invested exposure exceeds 95%."
        )
    )

    monkeypatch.setattr(
        decision_service,
        "validate_agent_decision",
        validator,
    )

    with pytest.raises(
        RiskValidationError,
        match="Total invested exposure",
    ):
        orchestrator.generate_agent_decision(
            db=Mock(),
            competition_id=uuid4(),
            agent_id=uuid4(),
            as_of_date=date(2026, 10, 30),
        )

    validator.assert_called_once_with(
        decision=expected_decision,
        context=market_context,
    )


def test_risk_validation_runs_after_strategy_generation(
    monkeypatch,
    orchestrator,
    market_context,
):
    from app.services.trading import decision_service

    expected_decision = AgentDecision(
        as_of_date="2026-10-30",
        summary="Safe trading decision.",
        decisions=[],
    )

    strategy = Mock()
    strategy.generate_decision.return_value = expected_decision

    monkeypatch.setattr(
        decision_service,
        "build_agent_market_context",
        Mock(return_value=market_context),
    )

    monkeypatch.setattr(
        decision_service.StrategyRegistry,
        "get",
        Mock(return_value=strategy),
    )

    validator = Mock()

    monkeypatch.setattr(
        decision_service,
        "validate_agent_decision",
        validator,
    )

    result = orchestrator.generate_agent_decision(
        db=Mock(),
        competition_id=uuid4(),
        agent_id=uuid4(),
        as_of_date=date(2026, 10, 30),
    )

    assert result == expected_decision

    strategy.generate_decision.assert_called_once_with(market_context)

    validator.assert_called_once_with(
        decision=expected_decision,
        context=market_context,
    )

def test_generate_and_submit_converts_buy_sell_and_ignores_hold(
    monkeypatch,
    orchestrator,
):
    from app.services.trading import decision_service

    decision = AgentDecision(
        as_of_date="2026-10-30",
        summary="Three decisions: two trades and one hold.",
        decisions=[
            AgentTradeDecision(
                symbol="NVDA",
                action="buy",
                quantity=2,
                confidence=0.9,
                rationale="Positive momentum.",
            ),
            AgentTradeDecision(
                symbol="AAPL",
                action="sell",
                quantity=1,
                confidence=0.8,
                rationale="Trend reversal.",
            ),
            AgentTradeDecision(
                symbol="MSFT",
                action="hold",
                confidence=0.7,
                rationale="No clear signal.",
            ),
        ],
    )

    monkeypatch.setattr(
        orchestrator,
        "generate_agent_decision",
        Mock(return_value=decision),
    )

    created_orders = [Mock(), Mock()]
    submit_batch = Mock(return_value=created_orders)

    monkeypatch.setattr(
        decision_service,
        "submit_order_batch",
        submit_batch,
    )

    db = Mock()
    competition_id = uuid4()
    agent_id = uuid4()
    as_of_date = date(2026, 10, 30)

    result_decision, result_orders = (
        orchestrator.generate_and_submit_agent_orders(
            db=db,
            competition_id=competition_id,
            agent_id=agent_id,
            as_of_date=as_of_date,
        )
    )

    assert result_decision == decision
    assert result_orders == created_orders

    submit_batch.assert_called_once()

    call_kwargs = submit_batch.call_args.kwargs

    assert call_kwargs["db"] is db
    assert call_kwargs["competition_id"] == competition_id
    assert call_kwargs["agent_id"] == agent_id

    orders = call_kwargs["orders"]

    assert len(orders) == 2

    assert orders[0].stock_symbol == "NVDA"
    assert orders[0].side == "buy"
    assert orders[0].order_type == "market"
    assert orders[0].quantity == 2

    assert orders[1].stock_symbol == "AAPL"
    assert orders[1].side == "sell"
    assert orders[1].order_type == "market"
    assert orders[1].quantity == 1


def test_generate_and_submit_returns_empty_list_for_hold_only(
    monkeypatch,
    orchestrator,
):
    from app.services.trading import decision_service

    decision = AgentDecision(
        as_of_date="2026-10-30",
        summary="No trades are necessary.",
        decisions=[
            AgentTradeDecision(
                symbol="NVDA",
                action="hold",
                confidence=0.9,
                rationale="Maintain current position.",
            ),
        ],
    )

    monkeypatch.setattr(
        orchestrator,
        "generate_agent_decision",
        Mock(return_value=decision),
    )

    submit_batch = Mock()

    monkeypatch.setattr(
        decision_service,
        "submit_order_batch",
        submit_batch,
    )

    result_decision, result_orders = (
        orchestrator.generate_and_submit_agent_orders(
            db=Mock(),
            competition_id=uuid4(),
            agent_id=uuid4(),
            as_of_date=date(2026, 10, 30),
        )
    )

    assert result_decision == decision
    assert result_orders == []
    submit_batch.assert_not_called()


def test_generate_and_submit_returns_empty_list_for_no_decisions(
    monkeypatch,
    orchestrator,
):
    from app.services.trading import decision_service

    decision = AgentDecision(
        as_of_date="2026-10-30",
        summary="No trading signals were generated.",
        decisions=[],
    )

    monkeypatch.setattr(
        orchestrator,
        "generate_agent_decision",
        Mock(return_value=decision),
    )

    submit_batch = Mock()

    monkeypatch.setattr(
        decision_service,
        "submit_order_batch",
        submit_batch,
    )

    result_decision, result_orders = (
        orchestrator.generate_and_submit_agent_orders(
            db=Mock(),
            competition_id=uuid4(),
            agent_id=uuid4(),
            as_of_date=date(2026, 10, 30),
        )
    )

    assert result_decision == decision
    assert result_orders == []
    submit_batch.assert_not_called()


def test_generate_and_submit_propagates_brokerage_failure(
    monkeypatch,
    orchestrator,
):
    from app.services.trading import decision_service

    decision = AgentDecision(
        as_of_date="2026-10-30",
        summary="Buy NVIDIA.",
        decisions=[
            AgentTradeDecision(
                symbol="NVDA",
                action="buy",
                quantity=2,
                confidence=0.9,
                rationale="Positive momentum.",
            ),
        ],
    )

    monkeypatch.setattr(
        orchestrator,
        "generate_agent_decision",
        Mock(return_value=decision),
    )

    monkeypatch.setattr(
        decision_service,
        "submit_order_batch",
        Mock(
            side_effect=HTTPException(
                status_code=400,
                detail="Insufficient available cash.",
            )
        ),
    )

    with pytest.raises(HTTPException) as exc:
        orchestrator.generate_and_submit_agent_orders(
            db=Mock(),
            competition_id=uuid4(),
            agent_id=uuid4(),
            as_of_date=date(2026, 10, 30),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Insufficient available cash."

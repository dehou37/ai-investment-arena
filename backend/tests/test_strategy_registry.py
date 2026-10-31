
from datetime import date

import pytest

from app.schemas.agent_decision import AgentDecision
from app.services.trading.strategies.base import TradingStrategy
from app.services.trading.strategies.registry import StrategyRegistry


class DummyStrategy(TradingStrategy):
    strategy_type = "test_dummy"

    def generate_decision(self, context):
        return AgentDecision(
            as_of_date=date(2026, 10, 30),
            summary="Test strategy decision.",
            decisions=[],
        )


def test_register_strategy():
    StrategyRegistry.register(DummyStrategy)

    assert "test_dummy" in StrategyRegistry.supported_strategies()


def test_get_registered_strategy():
    strategy = StrategyRegistry.get("test_dummy")

    assert isinstance(strategy, DummyStrategy)


def test_strategy_can_generate_decision():
    strategy = StrategyRegistry.get("test_dummy")

    decision = strategy.generate_decision({})

    assert isinstance(decision, AgentDecision)
    assert decision.as_of_date == date(2026, 10, 30)


def test_duplicate_registration_is_rejected():
    with pytest.raises(ValueError, match="already registered"):
        StrategyRegistry.register(DummyStrategy)


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError, match="Unknown strategy type"):
        StrategyRegistry.get("does_not_exist")


def test_invalid_strategy_class_is_rejected():
    class InvalidStrategy:
        strategy_type = "invalid"

    with pytest.raises(TypeError):
        StrategyRegistry.register(InvalidStrategy)

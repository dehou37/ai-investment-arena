
import json

import pytest

from app.schemas.agent_decision import AgentDecision
from app.schemas.llm_decision import LLMAgentDecisionOutput
from app.services.trading.strategies.llm_analyst import (
    LLMAnalystStrategy,
    LLMStrategyError,
)


class FakeOllamaClient:
    """Mock Ollama client that returns a predefined response."""

    def __init__(self, response: str):
        self.response = response
        self.last_messages = None

    def chat(self, messages, response_schema):
        self.last_messages = messages
        return self.response


def build_market_context():
    return {
        "as_of_date": "2026-10-30",
        "expected_latest_session_date": "2026-10-30",
        "competition": {
            "name": "AI Investment Arena - Season 2",
            "initial_cash": 10000.0,
            "duration_days": 90,
            "start_date": "2026-10-30",
            "scheduled_end_date": "2027-01-28",
            "benchmark_symbol": "SPY",
        },
        "agent": {
            "name": "AI Analyst",
            "strategy_type": "llm_analyst",
            "description": "LLM-powered investment analyst",
            "config": {},
        },
        "universe": {
            "stock_count": 2,
            "stocks": [
                {
                    "symbol": "NVDA",
                    "sector": "Technology",
                    "latest_price": 200.0,
                    "latest_bar_date": "2026-10-30",
                    "expected_latest_session_date": "2026-10-30",
                    "data_status": "current",
                    "indicators": {
                        "sma_20": 195.0,
                        "sma_50": 185.0,
                        "rsi_14": 58.0,
                        "momentum_20d": 0.05,
                        "volatility_20d": 0.30,
                    },
                    "history": [{"date": "2026-10-30"}],
                },
                {
                    "symbol": "AAPL",
                    "sector": "Technology",
                    "latest_price": 250.0,
                    "latest_bar_date": "2026-10-30",
                    "expected_latest_session_date": "2026-10-30",
                    "data_status": "current",
                    "indicators": {
                        "sma_20": 248.0,
                        "sma_50": 245.0,
                        "rsi_14": 55.0,
                        "momentum_20d": 0.02,
                        "volatility_20d": 0.20,
                    },
                    "history": [{"date": "2026-10-30"}],
                },
            ],
        },
        "benchmark": {
            "symbol": "SPY",
            "latest_price": 600.0,
            "data_status": "current",
            "indicators": {
                "sma_20": 595.0,
                "sma_50": 590.0,
                "rsi_14": 54.0,
                "momentum_20d": 0.015,
                "volatility_20d": 0.15,
            },
        },
        "portfolio": {
            "cash_balance": 10000.0,
            "holdings": [],
        },
        "trading_constraints": {
            "long_only": True,
            "whole_shares_only": True,
            "fractional_shares_allowed": False,
            "margin_allowed": False,
            "short_selling_allowed": False,
        },
    }


def make_response(decisions=None, as_of_date="2026-10-30"):
    return json.dumps({
        "as_of_date": as_of_date,
        "summary": "Positive market conditions support selective buying.",
        "decisions": decisions if decisions is not None else [
            {
                "symbol": "NVDA",
                "action": "buy",
                "quantity": 2,
                "confidence": 0.85,
                "rationale": "Positive momentum and price above moving averages.",
            },
            {
                "symbol": "AAPL",
                "action": "hold",
                "quantity": None,
                "confidence": 0.70,
                "rationale": "No compelling trading signal.",
            },
        ],
    })


def test_generates_valid_agent_decision():
    client = FakeOllamaClient(make_response())
    strategy = LLMAnalystStrategy(ollama_client=client)

    result = strategy.generate_decision(build_market_context())

    assert isinstance(result, AgentDecision)
    assert result.as_of_date.isoformat() == "2026-10-30"
    assert len(result.decisions) == 2
    assert result.decisions[0].symbol == "NVDA"
    assert result.decisions[0].action == "buy"


def test_rejects_unsupported_stock_symbol():
    decisions = [
        {
            "symbol": "GME",
            "action": "buy",
            "quantity": 1,
            "confidence": 0.8,
            "rationale": "Positive momentum.",
        }
    ]

    client = FakeOllamaClient(make_response(decisions))
    strategy = LLMAnalystStrategy(ollama_client=client)

    with pytest.raises(LLMStrategyError, match="unsupported stock"):
        strategy.generate_decision(build_market_context())


def test_rejects_stale_stock_data():
    context = build_market_context()
    context["universe"]["stocks"][0]["data_status"] = "stale_or_missing"

    decisions = [
        {
            "symbol": "NVDA",
            "action": "buy",
            "quantity": 1,
            "confidence": 0.8,
            "rationale": "Positive momentum.",
        }
    ]

    client = FakeOllamaClient(make_response(decisions))
    strategy = LLMAnalystStrategy(ollama_client=client)

    with pytest.raises(LLMStrategyError, match="stale or missing"):
        strategy.generate_decision(context)


def test_rejects_selling_more_shares_than_held():
    context = build_market_context()
    context["portfolio"]["holdings"] = [
        {
            "symbol": "NVDA",
            "quantity": 2,
            "average_entry_price": 190.0,
        }
    ]

    decisions = [
        {
            "symbol": "NVDA",
            "action": "sell",
            "quantity": 3,
            "confidence": 0.8,
            "rationale": "Reducing exposure.",
        }
    ]

    client = FakeOllamaClient(make_response(decisions))
    strategy = LLMAnalystStrategy(ollama_client=client)

    with pytest.raises(LLMStrategyError, match="selling more shares"):
        strategy.generate_decision(context)


def test_rejects_wrong_analysis_date():
    client = FakeOllamaClient(
        make_response(as_of_date="2026-10-29")
    )
    strategy = LLMAnalystStrategy(ollama_client=client)

    with pytest.raises(LLMStrategyError, match="decision date"):
        strategy.generate_decision(build_market_context())


def test_prompt_excludes_historical_ohlcv_bars():
    client = FakeOllamaClient(make_response())
    strategy = LLMAnalystStrategy(ollama_client=client)

    strategy.generate_decision(build_market_context())

    assert client.last_messages is not None

    user_message = client.last_messages[1]["content"]

    assert '"history"' not in user_message
    assert '"sma_20"' in user_message
    assert '"momentum_20d"' in user_message


def test_prompt_includes_competition_horizon():
    client = FakeOllamaClient(make_response())
    strategy = LLMAnalystStrategy(ollama_client=client)

    strategy.generate_decision(build_market_context())

    user_message = client.last_messages[1]["content"]

    assert '"start_date":"2026-10-30"' in user_message
    assert '"scheduled_end_date":"2027-01-28"' in user_message


def test_rejects_invalid_llm_json():
    client = FakeOllamaClient("This is not valid JSON")
    strategy = LLMAnalystStrategy(ollama_client=client)

    with pytest.raises(LLMStrategyError, match="invalid decision"):
        strategy.generate_decision(build_market_context())


def test_llm_output_schema_limits_response_text_length():
    response = json.loads(make_response())
    response["summary"] = "s" * 301

    with pytest.raises(ValueError):
        LLMAgentDecisionOutput.model_validate(response)

    response = json.loads(make_response())
    response["decisions"][0]["rationale"] = "r" * 81

    with pytest.raises(ValueError):
        LLMAgentDecisionOutput.model_validate(response)


def test_generates_valid_sell_decision():
    context = build_market_context()
    context["portfolio"]["holdings"] = [
        {
            "symbol": "NVDA",
            "quantity": 5,
            "average_entry_price": 190.0,
        }
    ]

    decisions = [
        {
            "symbol": "NVDA",
            "action": "sell",
            "quantity": 3,
            "confidence": 0.9,
            "rationale": "Reducing exposure after weakening momentum.",
        }
    ]

    client = FakeOllamaClient(make_response(decisions))
    strategy = LLMAnalystStrategy(ollama_client=client)

    result = strategy.generate_decision(context)

    assert len(result.decisions) == 1
    assert result.decisions[0].action == "sell"
    assert result.decisions[0].quantity == 3


def test_rejects_selling_stock_not_held():
    context = build_market_context()

    decisions = [
        {
            "symbol": "NVDA",
            "action": "sell",
            "quantity": 1,
            "confidence": 0.9,
            "rationale": "Taking profits.",
        }
    ]

    client = FakeOllamaClient(make_response(decisions))
    strategy = LLMAnalystStrategy(ollama_client=client)

    with pytest.raises(LLMStrategyError):
        strategy.generate_decision(context)


def test_allows_hold_decision_for_stale_stock():
    context = build_market_context()
    context["universe"]["stocks"][0]["data_status"] = "stale_or_missing"

    decisions = [
        {
            "symbol": "NVDA",
            "action": "hold",
            "quantity": None,
            "confidence": 0.8,
            "rationale": "Retain the existing position while awaiting fresh data.",
        }
    ]

    client = FakeOllamaClient(make_response(decisions))
    strategy = LLMAnalystStrategy(ollama_client=client)

    result = strategy.generate_decision(context)

    assert result.decisions[0].action == "hold"


def test_rejects_sell_quantity_of_zero():
    context = build_market_context()
    context["portfolio"]["holdings"] = [
        {
            "symbol": "NVDA",
            "quantity": 5,
            "average_entry_price": 190.0,
        }
    ]

    decisions = [
        {
            "symbol": "NVDA",
            "action": "sell",
            "quantity": 0,
            "confidence": 0.9,
            "rationale": "Reducing exposure.",
        }
    ]

    client = FakeOllamaClient(make_response(decisions))
    strategy = LLMAnalystStrategy(ollama_client=client)

    with pytest.raises(LLMStrategyError):
        strategy.generate_decision(context)


def test_rejects_malformed_stock_context():
    context = build_market_context()
    context["universe"]["stocks"][0] = None

    client = FakeOllamaClient(make_response())
    strategy = LLMAnalystStrategy(ollama_client=client)

    with pytest.raises(LLMStrategyError):
        strategy.generate_decision(context)


def test_rejects_malformed_holding_when_selling():
    context = build_market_context()
    context["portfolio"]["holdings"] = [
        {
            "symbol": "NVDA",
            # Deliberately missing quantity.
            "average_entry_price": 190.0,
        }
    ]

    decisions = [
        {
            "symbol": "NVDA",
            "action": "sell",
            "quantity": 1,
            "confidence": 0.9,
            "rationale": "Reducing exposure.",
        }
    ]

    client = FakeOllamaClient(make_response(decisions))
    strategy = LLMAnalystStrategy(ollama_client=client)

    with pytest.raises(LLMStrategyError):
        strategy.generate_decision(context)


def test_includes_stale_benchmark_status_in_prompt():
    context = build_market_context()
    context["benchmark"]["data_status"] = "stale_or_missing"

    client = FakeOllamaClient(make_response())
    strategy = LLMAnalystStrategy(ollama_client=client)

    strategy.generate_decision(context)

    user_message = client.last_messages[1]["content"]

    assert '"data_status":"stale_or_missing"' in user_message
    assert '"symbol":"SPY"' in user_message

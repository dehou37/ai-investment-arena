
import pytest

from app.services.trading.strategies.risk_managed import (
    RiskManagedStrategy,
)


def create_test_context():
    return {
        "competition": {
            "initial_cash": 10000.0,
        },
        "agent": {
            "name": "Guardian",
            "strategy_type": "risk_managed",
            "config": {},
        },
        "as_of_date": "2026-10-30",
        "portfolio": {
            "cash_balance": 10000.0,
            "holdings": [],
        },
        "universe": {
            "stock_count": 5,
            "stocks": [
                {
                    "symbol": "NVDA",
                    "latest_price": 120.0,
                    "data_status": "current",
                    "indicators": {
                        "sma_20": 110.0,
                        "sma_50": 100.0,
                        "momentum_20d": 0.15,
                        "volatility_20d": 0.25,
                    },
                },
                {
                    "symbol": "AAPL",
                    "latest_price": 220.0,
                    "data_status": "current",
                    "indicators": {
                        "sma_20": 210.0,
                        "sma_50": 200.0,
                        "momentum_20d": 0.08,
                        "volatility_20d": 0.15,
                    },
                },
                {
                    "symbol": "MSFT",
                    "latest_price": 300.0,
                    "data_status": "current",
                    "indicators": {
                        "sma_20": 310.0,
                        "sma_50": 290.0,
                        "momentum_20d": 0.10,
                        "volatility_20d": 0.20,
                    },
                },
                {
                    "symbol": "INTC",
                    "latest_price": 60.0,
                    "data_status": "stale_or_missing",
                    "indicators": {
                        "sma_20": 55.0,
                        "sma_50": 50.0,
                        "momentum_20d": 0.12,
                        "volatility_20d": 0.10,
                    },
                },
                {
                    "symbol": "AMD",
                    "latest_price": 150.0,
                    "data_status": "current",
                    "indicators": {
                        "sma_20": 140.0,
                        "sma_50": 130.0,
                        "momentum_20d": 0.12,
                        "volatility_20d": 0.55,
                    },
                },
            ],
        },
    }


def test_only_selects_stocks_meeting_all_risk_conditions():
    strategy = RiskManagedStrategy()

    result = strategy.generate_decision(create_test_context())

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert symbols == {"NVDA", "AAPL"}


def test_ranks_candidates_by_lowest_volatility():
    strategy = RiskManagedStrategy()

    result = strategy.generate_decision(create_test_context())

    assert result.decisions[0].symbol == "AAPL"
    assert result.decisions[1].symbol == "NVDA"


def test_only_generates_buy_decisions():
    strategy = RiskManagedStrategy()

    result = strategy.generate_decision(create_test_context())

    assert all(
        decision.action == "buy"
        for decision in result.decisions
    )


def test_only_uses_whole_shares():
    strategy = RiskManagedStrategy()

    result = strategy.generate_decision(create_test_context())

    assert all(
        isinstance(decision.quantity, int)
        and decision.quantity > 0
        for decision in result.decisions
    )


def test_existing_holdings_are_excluded():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    context["portfolio"]["holdings"] = [
        {
            "symbol": "AAPL",
            "quantity": 2,
            "average_entry_price": 200.0,
        }
    ]

    result = strategy.generate_decision(context)

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert "AAPL" not in symbols


def test_stale_market_data_is_excluded():
    strategy = RiskManagedStrategy()

    result = strategy.generate_decision(create_test_context())

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert "INTC" not in symbols


def test_excessive_volatility_is_excluded():
    strategy = RiskManagedStrategy()

    result = strategy.generate_decision(create_test_context())

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert "AMD" not in symbols


def test_configurable_volatility_threshold_is_respected():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_volatility": 0.20,
    }

    result = strategy.generate_decision(context)

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert symbols == {"AAPL"}


def test_maximum_new_positions_is_respected():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_new_positions": 1,
    }

    result = strategy.generate_decision(context)

    assert len(result.decisions) == 1
    assert result.decisions[0].symbol == "AAPL"


def test_position_size_does_not_exceed_configured_cap():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_position_fraction": 0.05,
    }

    result = strategy.generate_decision(context)

    prices = {
        stock["symbol"]: stock["latest_price"]
        for stock in context["universe"]["stocks"]
    }

    for decision in result.decisions:
        reserved_cost = (
            decision.quantity
            * prices[decision.symbol]
            * strategy.ORDER_RESERVATION_BUFFER
        )

        assert reserved_cost <= 10000.0 * 0.05


def test_buying_power_is_not_exceeded():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    result = strategy.generate_decision(context)

    prices = {
        stock["symbol"]: stock["latest_price"]
        for stock in context["universe"]["stocks"]
    }

    reserved_cost = sum(
        decision.quantity
        * prices[decision.symbol]
        * strategy.ORDER_RESERVATION_BUFFER
        for decision in result.decisions
    )

    assert reserved_cost <= context["portfolio"]["cash_balance"]


def test_no_cash_generates_no_decisions():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    context["portfolio"]["cash_balance"] = 0

    result = strategy.generate_decision(context)

    assert result.decisions == []


def test_missing_volatility_indicator_excludes_stock():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    context["universe"]["stocks"][0]["indicators"][
        "volatility_20d"
    ] = None

    result = strategy.generate_decision(context)

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert "NVDA" not in symbols


def test_invalid_allocation_fraction_is_rejected():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "allocation_fraction": 1.5,
    }

    with pytest.raises(ValueError):
        strategy.generate_decision(context)


def test_invalid_position_fraction_is_rejected():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_position_fraction": 0,
    }

    with pytest.raises(ValueError):
        strategy.generate_decision(context)


def test_invalid_maximum_volatility_is_rejected():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_volatility": float("nan"),
    }

    with pytest.raises(ValueError):
        strategy.generate_decision(context)


def test_invalid_maximum_positions_is_rejected():
    strategy = RiskManagedStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_new_positions": 0,
    }

    with pytest.raises(ValueError):
        strategy.generate_decision(context)

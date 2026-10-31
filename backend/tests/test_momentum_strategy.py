
import pytest

from app.services.trading.strategies.momentum import MomentumStrategy


def create_test_context():
    return {
        "competition": {
            "initial_cash": 10000.0,
        },
        "agent": {
            "name": "Momentum",
            "strategy_type": "momentum",
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
                    "latest_price": 100.0,
                    "data_status": "current",
                    "indicators": {
                        "momentum_20d": 0.15,
                        "sma_20": 110.0,
                        "sma_50": 100.0,
                    },
                },
                {
                    "symbol": "AAPL",
                    "latest_price": 200.0,
                    "data_status": "current",
                    "indicators": {
                        "momentum_20d": 0.08,
                        "sma_20": 210.0,
                        "sma_50": 200.0,
                    },
                },
                {
                    "symbol": "MSFT",
                    "latest_price": 300.0,
                    "data_status": "current",
                    "indicators": {
                        "momentum_20d": 0.05,
                        "sma_20": 290.0,
                        "sma_50": 300.0,
                    },
                },
                {
                    "symbol": "INTC",
                    "latest_price": 50.0,
                    "data_status": "stale_or_missing",
                    "indicators": {
                        "momentum_20d": 0.20,
                        "sma_20": 60.0,
                        "sma_50": 50.0,
                    },
                },
                {
                    "symbol": "AMD",
                    "latest_price": 150.0,
                    "data_status": "current",
                    "indicators": {
                        "momentum_20d": -0.05,
                        "sma_20": 160.0,
                        "sma_50": 150.0,
                    },
                },
            ],
        },
    }


def test_only_selects_qualifying_momentum_stocks():
    strategy = MomentumStrategy()

    result = strategy.generate_decision(create_test_context())

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert symbols == {"NVDA", "AAPL"}


def test_ranks_candidates_by_momentum():
    strategy = MomentumStrategy()

    result = strategy.generate_decision(create_test_context())

    assert result.decisions[0].symbol == "NVDA"
    assert result.decisions[1].symbol == "AAPL"


def test_only_generates_buy_decisions():
    strategy = MomentumStrategy()

    result = strategy.generate_decision(create_test_context())

    assert all(
        decision.action == "buy"
        for decision in result.decisions
    )


def test_only_uses_whole_shares():
    strategy = MomentumStrategy()

    result = strategy.generate_decision(create_test_context())

    assert all(
        isinstance(decision.quantity, int)
        and decision.quantity > 0
        for decision in result.decisions
    )


def test_existing_holdings_are_excluded():
    strategy = MomentumStrategy()
    context = create_test_context()

    context["portfolio"]["holdings"] = [
        {
            "symbol": "NVDA",
            "quantity": 5,
            "average_entry_price": 100.0,
        }
    ]

    result = strategy.generate_decision(context)

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert "NVDA" not in symbols


def test_maximum_new_positions_is_respected():
    strategy = MomentumStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_new_positions": 1,
    }

    result = strategy.generate_decision(context)

    assert len(result.decisions) == 1
    assert result.decisions[0].symbol == "NVDA"


def test_minimum_momentum_threshold_is_respected():
    strategy = MomentumStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "min_momentum": 0.10,
    }

    result = strategy.generate_decision(context)

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert symbols == {"NVDA"}


def test_buying_power_is_not_exceeded():
    strategy = MomentumStrategy()
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
    strategy = MomentumStrategy()
    context = create_test_context()

    context["portfolio"]["cash_balance"] = 0

    result = strategy.generate_decision(context)

    assert result.decisions == []


def test_invalid_allocation_fraction_is_rejected():
    strategy = MomentumStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "allocation_fraction": 1.5,
    }

    with pytest.raises(ValueError):
        strategy.generate_decision(context)


def test_invalid_maximum_positions_is_rejected():
    strategy = MomentumStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_new_positions": 0,
    }

    with pytest.raises(ValueError):
        strategy.generate_decision(context)

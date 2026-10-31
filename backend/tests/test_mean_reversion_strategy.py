
import pytest

from app.services.trading.strategies.mean_reversion import (
    MeanReversionStrategy,
)


def create_test_context():
    return {
        "competition": {
            "initial_cash": 10000.0,
        },
        "agent": {
            "name": "Contrarian",
            "strategy_type": "mean_reversion",
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
                        "rsi_14": 20.0,
                        "momentum_20d": -0.15,
                        "sma_20": 110.0,
                    },
                },
                {
                    "symbol": "AAPL",
                    "latest_price": 200.0,
                    "data_status": "current",
                    "indicators": {
                        "rsi_14": 25.0,
                        "momentum_20d": -0.08,
                        "sma_20": 210.0,
                    },
                },
                {
                    "symbol": "MSFT",
                    "latest_price": 300.0,
                    "data_status": "current",
                    "indicators": {
                        "rsi_14": 35.0,
                        "momentum_20d": -0.10,
                        "sma_20": 310.0,
                    },
                },
                {
                    "symbol": "INTC",
                    "latest_price": 50.0,
                    "data_status": "stale_or_missing",
                    "indicators": {
                        "rsi_14": 15.0,
                        "momentum_20d": -0.20,
                        "sma_20": 60.0,
                    },
                },
                {
                    "symbol": "AMD",
                    "latest_price": 150.0,
                    "data_status": "current",
                    "indicators": {
                        "rsi_14": 22.0,
                        "momentum_20d": 0.05,
                        "sma_20": 160.0,
                    },
                },
            ],
        },
    }


def test_only_selects_qualifying_stocks():
    strategy = MeanReversionStrategy()

    result = strategy.generate_decision(create_test_context())

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert symbols == {"NVDA", "AAPL"}


def test_ranks_candidates_by_lowest_rsi():
    strategy = MeanReversionStrategy()

    result = strategy.generate_decision(create_test_context())

    assert result.decisions[0].symbol == "NVDA"
    assert result.decisions[1].symbol == "AAPL"


def test_only_generates_buy_decisions():
    strategy = MeanReversionStrategy()

    result = strategy.generate_decision(create_test_context())

    assert all(
        decision.action == "buy"
        for decision in result.decisions
    )


def test_only_uses_whole_shares():
    strategy = MeanReversionStrategy()

    result = strategy.generate_decision(create_test_context())

    assert all(
        isinstance(decision.quantity, int)
        and decision.quantity > 0
        for decision in result.decisions
    )


def test_existing_holdings_are_excluded():
    strategy = MeanReversionStrategy()
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
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_new_positions": 1,
    }

    result = strategy.generate_decision(context)

    assert len(result.decisions) == 1
    assert result.decisions[0].symbol == "NVDA"


def test_configurable_rsi_threshold_is_respected():
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_rsi": 23.0,
    }

    result = strategy.generate_decision(context)

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert symbols == {"NVDA"}


def test_buying_power_is_not_exceeded():
    strategy = MeanReversionStrategy()
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
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["portfolio"]["cash_balance"] = 0

    result = strategy.generate_decision(context)

    assert result.decisions == []


def test_invalid_allocation_fraction_is_rejected():
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "allocation_fraction": 1.5,
    }

    with pytest.raises(ValueError):
        strategy.generate_decision(context)


def test_invalid_rsi_threshold_is_rejected():
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_rsi": 101,
    }

    with pytest.raises(ValueError):
        strategy.generate_decision(context)


def test_invalid_maximum_positions_is_rejected():
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "max_new_positions": 0,
    }

    with pytest.raises(ValueError):
        strategy.generate_decision(context)


def test_sells_entire_position_when_rsi_reaches_exit_threshold():
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["portfolio"]["holdings"] = [
        {
            "symbol": "NVDA",
            "quantity": 5,
            "average_entry_price": 100.0,
        }
    ]

    context["universe"]["stocks"][0]["indicators"]["rsi_14"] = 65.0

    result = strategy.generate_decision(context)

    sell_decisions = [
        decision for decision in result.decisions
        if decision.action == "sell"
    ]

    assert len(sell_decisions) == 1
    assert sell_decisions[0].symbol == "NVDA"
    assert sell_decisions[0].quantity == 5


def test_custom_exit_rsi_threshold_is_respected():
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "exit_rsi": 55.0,
    }

    context["portfolio"]["holdings"] = [
        {
            "symbol": "NVDA",
            "quantity": 5,
            "average_entry_price": 100.0,
        }
    ]

    context["universe"]["stocks"][0]["indicators"]["rsi_14"] = 57.0

    result = strategy.generate_decision(context)

    sell_decisions = [
        decision for decision in result.decisions
        if decision.action == "sell"
    ]

    assert len(sell_decisions) == 1
    assert sell_decisions[0].quantity == 5


def test_does_not_sell_when_rsi_is_below_exit_threshold():
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["portfolio"]["holdings"] = [
        {
            "symbol": "NVDA",
            "quantity": 5,
            "average_entry_price": 100.0,
        }
    ]

    context["universe"]["stocks"][0]["indicators"]["rsi_14"] = 45.0

    result = strategy.generate_decision(context)

    sell_decisions = [
        decision for decision in result.decisions
        if decision.action == "sell"
    ]

    assert sell_decisions == []


def test_does_not_sell_holding_with_stale_market_data():
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["portfolio"]["holdings"] = [
        {
            "symbol": "INTC",
            "quantity": 10,
            "average_entry_price": 50.0,
        }
    ]

    context["universe"]["stocks"][3]["indicators"]["rsi_14"] = 75.0

    result = strategy.generate_decision(context)

    sell_decisions = [
        decision for decision in result.decisions
        if decision.action == "sell"
    ]

    assert sell_decisions == []


def test_can_generate_sell_decisions_without_available_cash():
    strategy = MeanReversionStrategy()
    context = create_test_context()

    context["portfolio"]["cash_balance"] = 0.0

    context["portfolio"]["holdings"] = [
        {
            "symbol": "NVDA",
            "quantity": 5,
            "average_entry_price": 100.0,
        }
    ]

    context["universe"]["stocks"][0]["indicators"]["rsi_14"] = 65.0

    result = strategy.generate_decision(context)

    assert len(result.decisions) == 1
    assert result.decisions[0].symbol == "NVDA"
    assert result.decisions[0].action == "sell"
    assert result.decisions[0].quantity == 5

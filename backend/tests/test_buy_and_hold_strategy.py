
from app.services.trading.strategies.buy_and_hold import BuyAndHoldStrategy


def create_test_context():
    return {
        "competition": {
            "initial_cash": 10000.0,
        },
        "agent": {
            "name": "Warren",
            "strategy_type": "buy_and_hold",
            "config": {},
        },
        "as_of_date": "2026-10-30",
        "portfolio": {
            "cash_balance": 10000.0,
            "holdings": [],
        },
        "universe": {
            "stock_count": 3,
            "stocks": [
                {
                    "symbol": "AAPL",
                    "latest_price": 100.0,
                    "data_status": "current",
                },
                {
                    "symbol": "MSFT",
                    "latest_price": 200.0,
                    "data_status": "current",
                },
                {
                    "symbol": "NVDA",
                    "latest_price": 10000.0,
                    "data_status": "current",
                },
            ],
        },
    }


def test_generates_buy_decisions():
    strategy = BuyAndHoldStrategy()
    context = create_test_context()

    result = strategy.generate_decision(context)

    assert len(result.decisions) == 2

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert symbols == {"AAPL", "MSFT"}


def test_only_generates_buy_decisions():
    strategy = BuyAndHoldStrategy()

    result = strategy.generate_decision(create_test_context())

    assert all(
        decision.action == "buy"
        for decision in result.decisions
    )


def test_only_uses_whole_shares():
    strategy = BuyAndHoldStrategy()

    result = strategy.generate_decision(create_test_context())

    assert all(
        isinstance(decision.quantity, int)
        and decision.quantity > 0
        for decision in result.decisions
    )


def test_existing_holdings_are_not_purchased_again():
    strategy = BuyAndHoldStrategy()
    context = create_test_context()

    context["portfolio"]["holdings"] = [
        {
            "symbol": "AAPL",
            "quantity": 5,
            "average_entry_price": 100.0,
        }
    ]

    result = strategy.generate_decision(context)

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert "AAPL" not in symbols


def test_stale_market_data_is_excluded():
    strategy = BuyAndHoldStrategy()
    context = create_test_context()

    context["universe"]["stocks"][0]["data_status"] = "stale_or_missing"

    result = strategy.generate_decision(context)

    symbols = {
        decision.symbol
        for decision in result.decisions
    }

    assert "AAPL" not in symbols


def test_does_not_overspend_buying_power():
    strategy = BuyAndHoldStrategy()
    context = create_test_context()

    result = strategy.generate_decision(context)

    reserved_cost = sum(
        decision.quantity
        * next(
            stock["latest_price"]
            for stock in context["universe"]["stocks"]
            if stock["symbol"] == decision.symbol
        )
        * strategy.ORDER_RESERVATION_BUFFER
        for decision in result.decisions
    )

    assert reserved_cost <= context["portfolio"]["cash_balance"]


def test_no_cash_generates_no_decisions():
    strategy = BuyAndHoldStrategy()
    context = create_test_context()

    context["portfolio"]["cash_balance"] = 0

    result = strategy.generate_decision(context)

    assert result.decisions == []


def test_invalid_allocation_fraction_is_rejected():
    strategy = BuyAndHoldStrategy()
    context = create_test_context()

    context["agent"]["config"] = {
        "allocation_fraction": 1.5,
    }

    import pytest

    with pytest.raises(ValueError):
        strategy.generate_decision(context)


def test_never_generates_sell_decisions():
    strategy = BuyAndHoldStrategy()
    context = create_test_context()

    context["portfolio"]["holdings"] = [
        {
            "symbol": "AAPL",
            "quantity": 10,
            "average_entry_price": 100.0,
        },
        {
            "symbol": "MSFT",
            "quantity": 5,
            "average_entry_price": 200.0,
        },
    ]

    result = strategy.generate_decision(context)

    sell_decisions = [
        decision
        for decision in result.decisions
        if decision.action == "sell"
    ]

    assert sell_decisions == []


def test_does_not_sell_even_when_holding_is_unprofitable():
    strategy = BuyAndHoldStrategy()
    context = create_test_context()

    context["portfolio"]["holdings"] = [
        {
            "symbol": "AAPL",
            "quantity": 10,
            "average_entry_price": 150.0,
        }
    ]

    result = strategy.generate_decision(context)

    sell_decisions = [
        decision
        for decision in result.decisions
        if decision.action == "sell"
    ]

    assert sell_decisions == []

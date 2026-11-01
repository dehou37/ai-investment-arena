
from datetime import date

import pytest

from app.schemas.agent_decision import (
    AgentDecision,
    AgentTradeDecision,
)
from app.services.trading.risk_service import (
    RiskValidationError,
    validate_agent_decision,
)


AS_OF_DATE = "2026-10-30"


def make_context(
    cash="10000",
    holdings=None,
    stock_prices=None,
    stale_symbols=None,
    open_orders=None,
):
    holdings = holdings or []
    open_orders = open_orders or []

    stock_prices = stock_prices or {
        "NVDA": "100",
        "AAPL": "100",
        "MSFT": "100",
        "GOOGL": "100",
        "AMZN": "100",
    }

    stale_symbols = stale_symbols or []

    stocks = []

    for symbol, price in stock_prices.items():
        stocks.append({
            "symbol": symbol,
            "latest_price": price,
            "data_status": (
                "stale_or_missing"
                if symbol in stale_symbols
                else "current"
            ),
        })

    return {
        "as_of_date": AS_OF_DATE,
        "portfolio": {
            "cash_balance": cash,
            "holdings": holdings,
            "open_orders": open_orders,
        },
        "universe": {
            "stocks": stocks,
        },
        "trading_constraints": {
            "long_only": True,
            "whole_shares_only": True,
            "fractional_shares_allowed": False,
            "margin_allowed": False,
            "short_selling_allowed": False,
        },
    }


def make_decision(*trades):
    return AgentDecision(
        as_of_date=date.fromisoformat(AS_OF_DATE),
        summary="Risk validation test.",
        decisions=list(trades),
    )


def trade(symbol, action, quantity=None):
    return AgentTradeDecision(
        symbol=symbol,
        action=action,
        quantity=quantity,
        confidence=0.9,
        rationale="Test decision.",
    )


def test_accepts_buy_within_risk_limits():
    context = make_context()

    decision = make_decision(
        trade("NVDA", "buy", 10),
    )

    validate_agent_decision(decision, context)


def test_rejects_single_stock_allocation_above_33_percent():
    context = make_context()

    decision = make_decision(
        trade("NVDA", "buy", 34),
    )

    with pytest.raises(
        RiskValidationError,
        match="maximum allowed allocation",
    ):
        validate_agent_decision(decision, context)


def test_accepts_single_stock_allocation_at_exactly_33_percent():
    context = make_context()

    decision = make_decision(
        trade("NVDA", "buy", 33),
    )

    validate_agent_decision(decision, context)


def test_rejects_total_exposure_above_95_percent():
    context = make_context()

    decision = make_decision(
        trade("NVDA", "buy", 20),
        trade("AAPL", "buy", 20),
        trade("MSFT", "buy", 20),
        trade("GOOGL", "buy", 20),
        trade("AMZN", "buy", 16),
    )

    with pytest.raises(
        RiskValidationError,
        match="Total invested exposure",
    ):
        validate_agent_decision(decision, context)


def test_accepts_total_exposure_at_exactly_95_percent():
    context = make_context()

    decision = make_decision(
        trade("NVDA", "buy", 20),
        trade("AAPL", "buy", 20),
        trade("MSFT", "buy", 20),
        trade("GOOGL", "buy", 20),
        trade("AMZN", "buy", 15),
    )

    validate_agent_decision(decision, context)


def test_rejects_stock_outside_competition_universe():
    context = make_context()

    decision = make_decision(
        trade("TSLA", "buy", 1),
    )

    with pytest.raises(
        RiskValidationError,
        match="frozen stock universe",
    ):
        validate_agent_decision(decision, context)


def test_rejects_stale_stock_data():
    context = make_context(
        stale_symbols=["NVDA"],
    )

    decision = make_decision(
        trade("NVDA", "buy", 1),
    )

    with pytest.raises(
        RiskValidationError,
        match="stale or missing",
    ):
        validate_agent_decision(decision, context)


def test_rejects_selling_more_shares_than_owned():
    context = make_context(
        holdings=[
            {
                "symbol": "NVDA",
                "quantity": 5,
                "average_entry_price": "100",
            },
        ],
    )

    decision = make_decision(
        trade("NVDA", "sell", 6),
    )

    with pytest.raises(
        RiskValidationError,
        match="only 5 shares are held",
    ):
        validate_agent_decision(decision, context)


def test_sell_reduces_projected_exposure():
    context = make_context(
        cash="8000",
        holdings=[
            {
                "symbol": "NVDA",
                "quantity": 20,
                "average_entry_price": "100",
            },
        ],
    )

    decision = make_decision(
        trade("NVDA", "sell", 5),
    )

    validate_agent_decision(decision, context)


def test_rejects_holdings_with_stale_market_data():
    context = make_context(
        cash="8000",
        holdings=[
            {
                "symbol": "NVDA",
                "quantity": 20,
                "average_entry_price": "100",
            },
        ],
        stale_symbols=["NVDA"],
    )

    decision = make_decision(
        trade("AAPL", "buy", 1),
    )

    with pytest.raises(
        RiskValidationError,
        match="Cannot calculate portfolio exposure",
    ):
        validate_agent_decision(decision, context)


def test_hold_decision_does_not_require_fresh_stock_data():
    context = make_context(
        stale_symbols=["NVDA"],
    )

    decision = make_decision(
        trade("NVDA", "hold"),
    )

    validate_agent_decision(decision, context)


def test_rejects_mismatched_decision_date():
    context = make_context()

    decision = AgentDecision(
        as_of_date=date(2026, 10, 29),
        summary="Wrong date.",
        decisions=[],
    )

    with pytest.raises(
        RiskValidationError,
        match="Decision date",
    ):
        validate_agent_decision(decision, context)


# ---------------------------------------------------------
# Outstanding order tests
# ---------------------------------------------------------


def test_outstanding_market_buy_uses_5_percent_buffer():
    context = make_context(
        open_orders=[
            {
                "symbol": "NVDA",
                "side": "buy",
                "order_type": "market",
                "quantity": 32,
                "remaining_quantity": 32,
                "limit_price": None,
                "status": "queued",
            },
        ],
    )

    decision = make_decision()

    # 32 * 100 * 1.05 = 3,360 (33.6% of equity).
    with pytest.raises(
        RiskValidationError,
        match="maximum allowed allocation",
    ):
        validate_agent_decision(decision, context)


def test_outstanding_limit_buy_uses_limit_price():
    context = make_context(
        open_orders=[
            {
                "symbol": "NVDA",
                "side": "buy",
                "order_type": "limit",
                "quantity": 33,
                "remaining_quantity": 33,
                "limit_price": "100",
                "status": "queued",
            },
        ],
    )

    decision = make_decision()

    # 33 * 100 = 3,300 (exactly 33% of equity).
    validate_agent_decision(decision, context)


def test_multiple_outstanding_buys_for_same_stock_are_combined():
    context = make_context(
        open_orders=[
            {
                "symbol": "NVDA",
                "side": "buy",
                "order_type": "limit",
                "quantity": 17,
                "remaining_quantity": 17,
                "limit_price": "100",
                "status": "queued",
            },
            {
                "symbol": "NVDA",
                "side": "buy",
                "order_type": "limit",
                "quantity": 17,
                "remaining_quantity": 17,
                "limit_price": "100",
                "status": "pending",
            },
        ],
    )

    decision = make_decision()

    # Combined exposure: 34 * 100 = 3,400 (34% of equity).
    with pytest.raises(
        RiskValidationError,
        match="maximum allowed allocation",
    ):
        validate_agent_decision(decision, context)


def test_outstanding_sell_does_not_reduce_projected_exposure():
    context = make_context(
        cash="6700",
        holdings=[
            {
                "symbol": "NVDA",
                "quantity": 33,
                "average_entry_price": "100",
            },
        ],
        open_orders=[
            {
                "symbol": "NVDA",
                "side": "sell",
                "order_type": "market",
                "quantity": 2,
                "remaining_quantity": 2,
                "limit_price": None,
                "status": "queued",
            },
        ],
    )

    decision = make_decision(
        trade("NVDA", "buy", 1),
    )

    # The pending SELL is not executed, so projected holdings remain
    # 34 shares after the proposed BUY: 34% of portfolio equity.
    with pytest.raises(
        RiskValidationError,
        match="maximum allowed allocation",
    ):
        validate_agent_decision(decision, context)


from datetime import date
from math import floor
from typing import Any

from app.schemas.agent_decision import AgentDecision, AgentTradeDecision
from app.services.trading.strategies.base import TradingStrategy


class BuyAndHoldStrategy(TradingStrategy):
    """
    Equal-weight buy-and-hold strategy.

    Rules:
    - Only considers stocks in the supplied competition universe.
    - Only buys stocks with current market data.
    - Allocates an equal target budget to each eligible stock.
    - Buys whole shares only.
    - Never sells.
    - Does not increase existing positions.
    - Preserves a cash buffer for order reservations and execution costs.

    This strategy does not submit orders.
    """

    strategy_type = "buy_and_hold"

    DEFAULT_ALLOCATION_FRACTION = 0.95
    ORDER_RESERVATION_BUFFER = 1.05

    def generate_decision(
        self,
        context: dict[str, Any],
    ) -> AgentDecision:

        competition = context["competition"]
        agent = context["agent"]
        portfolio = context["portfolio"]
        universe = context["universe"]

        as_of_date = date.fromisoformat(context["as_of_date"])

        initial_cash = float(competition["initial_cash"])
        available_cash = float(portfolio["cash_balance"])

        config = agent.get("config") or {}

        allocation_fraction = float(
            config.get(
                "allocation_fraction",
                self.DEFAULT_ALLOCATION_FRACTION,
            )
        )

        if not 0 < allocation_fraction <= 1:
            raise ValueError(
                "allocation_fraction must be greater than 0 "
                "and no greater than 1."
            )

        if initial_cash <= 0 or available_cash <= 0:
            return AgentDecision(
                as_of_date=as_of_date,
                summary="No available cash for new investments.",
                decisions=[],
            )

        # Identify stocks with usable, current market data.
        eligible_stocks = [
            stock
            for stock in universe["stocks"]
            if (
                stock.get("data_status") == "current"
                and stock.get("latest_price") is not None
                and float(stock["latest_price"]) > 0
            )
        ]

        if not eligible_stocks:
            return AgentDecision(
                as_of_date=as_of_date,
                summary="No stocks have usable current market data.",
                decisions=[],
            )

        # Identify existing positions.
        existing_holdings = {
            holding["symbol"].upper()
            for holding in portfolio["holdings"]
            if holding["quantity"] > 0
        }

        # Preserve the original equal-weight target across the universe.
        # Do not increase the target merely because a stock is already held.
        total_budget = min(
            initial_cash * allocation_fraction,
            available_cash / self.ORDER_RESERVATION_BUFFER,
        )

        target_per_stock = total_budget / len(eligible_stocks)

        decisions = []

        for stock in eligible_stocks:

            symbol = stock["symbol"].upper()

            # Buy-and-hold does not increase existing positions.
            if symbol in existing_holdings:
                continue

            latest_price = float(stock["latest_price"])

            # Include the order reservation buffer when calculating
            # the maximum affordable whole-share quantity.
            estimated_reserved_cost_per_share = (
                latest_price * self.ORDER_RESERVATION_BUFFER
            )

            quantity = floor(
                target_per_stock / estimated_reserved_cost_per_share
            )

            if quantity <= 0:
                continue

            decisions.append(
                AgentTradeDecision(
                    symbol=symbol,
                    action="buy",
                    quantity=quantity,
                    confidence=0.80,
                    rationale=(
                        "Initial equal-weight buy-and-hold allocation. "
                        "The strategy purchases whole shares and holds "
                        "the position rather than trading on short-term "
                        "price movements."
                    ),
                )
            )

        if not decisions:
            summary = (
                "No new positions were purchased. Existing holdings, "
                "share prices, or available cash prevented new allocations."
            )
        else:
            summary = (
                f"Generated {len(decisions)} initial buy orders using "
                "an equal-weight buy-and-hold allocation. "
                "Existing positions were left unchanged."
            )

        return AgentDecision(
            as_of_date=as_of_date,
            summary=summary,
            decisions=decisions,
        )

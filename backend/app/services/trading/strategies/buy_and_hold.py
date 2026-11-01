
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
    - Allocates an equal target budget across the eligible universe.
    - Maximum allocation per stock: 33% of portfolio equity.
    - Maximum total invested exposure: 95% of portfolio equity.
    - Buys whole shares only.
    - Never sells.
    - Does not increase existing positions.
    - Preserves a cash buffer for order reservations and execution costs.

    This strategy does not submit orders.
    """

    strategy_type = "buy_and_hold"

    DEFAULT_ALLOCATION_FRACTION = 0.95
    MAX_SINGLE_STOCK_ALLOCATION = 0.33
    MAX_TOTAL_INVESTED_EXPOSURE = 0.95
    ORDER_RESERVATION_BUFFER = 1.05

    def generate_decision(
        self,
        context: dict[str, Any],
    ) -> AgentDecision:

        agent = context["agent"]
        portfolio = context["portfolio"]
        universe = context["universe"]

        as_of_date = date.fromisoformat(context["as_of_date"])

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

        if available_cash <= 0:
            return AgentDecision(
                as_of_date=as_of_date,
                summary="No available cash for new investments.",
                decisions=[],
            )

        stocks = universe["stocks"]

        stock_by_symbol = {
            stock["symbol"].upper(): stock
            for stock in stocks
        }

        # Identify existing positions and calculate their current value.
        existing_holdings = set()
        existing_market_value = 0.0

        for holding in portfolio["holdings"]:
            quantity = int(holding["quantity"])

            if quantity <= 0:
                continue

            symbol = holding["symbol"].upper()
            existing_holdings.add(symbol)

            stock = stock_by_symbol.get(symbol)

            # Do not make new investment decisions when an existing
            # holding cannot be valued using current market data.
            if (
                stock is None
                or stock.get("data_status") != "current"
                or stock.get("latest_price") is None
                or float(stock["latest_price"]) <= 0
            ):
                return AgentDecision(
                    as_of_date=as_of_date,
                    summary=(
                        f"Unable to value existing holding {symbol} "
                        "using current market data. No new purchases generated."
                    ),
                    decisions=[],
                )

            existing_market_value += (
                float(stock["latest_price"]) * quantity
            )

        # Calculate current portfolio equity and remaining exposure.
        portfolio_equity = available_cash + existing_market_value

        if portfolio_equity <= 0:
            return AgentDecision(
                as_of_date=as_of_date,
                summary="Portfolio equity is insufficient for new investments.",
                decisions=[],
            )

        maximum_total_exposure = (
            portfolio_equity * self.MAX_TOTAL_INVESTED_EXPOSURE
        )

        remaining_exposure = max(
            0.0,
            maximum_total_exposure - existing_market_value,
        )

        maximum_single_stock_value = (
            portfolio_equity * self.MAX_SINGLE_STOCK_ALLOCATION
        )

        # Only consider stocks with usable, current market data.
        eligible_stocks = [
            stock
            for stock in stocks
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

        # Preserve equal weighting across the eligible universe.
        # Existing holdings remain part of the allocation denominator,
        # but are never increased.
        maximum_new_investment = min(
            portfolio_equity * allocation_fraction,
            available_cash / self.ORDER_RESERVATION_BUFFER,
            remaining_exposure / self.ORDER_RESERVATION_BUFFER,
        )

        target_per_stock = (
            maximum_new_investment / len(eligible_stocks)
        )

        decisions = []

        for stock in eligible_stocks:

            symbol = stock["symbol"].upper()

            if symbol in existing_holdings:
                continue

            latest_price = float(stock["latest_price"])

            # Respect the individual stock allocation limit.
            target_value = min(
                target_per_stock,
                maximum_single_stock_value
                / self.ORDER_RESERVATION_BUFFER,
            )

            estimated_reserved_cost_per_share = (
                latest_price * self.ORDER_RESERVATION_BUFFER
            )

            quantity = floor(
                target_value / estimated_reserved_cost_per_share
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
                        "The strategy purchases whole shares, respects "
                        "portfolio exposure limits, and holds the position "
                        "rather than trading on short-term price movements."
                    ),
                )
            )

        if not decisions:
            summary = (
                "No new positions were purchased. Existing holdings, "
                "allocation limits, share prices, or available cash "
                "prevented new allocations."
            )
        else:
            summary = (
                f"Generated {len(decisions)} initial buy decisions using "
                "an equal-weight buy-and-hold allocation. "
                "Existing positions were left unchanged."
            )

        return AgentDecision(
            as_of_date=as_of_date,
            summary=summary,
            decisions=decisions,
        )

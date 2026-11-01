
from datetime import date
from math import floor, isfinite
from typing import Any

from app.schemas.agent_decision import AgentDecision, AgentTradeDecision
from app.services.trading.strategies.base import TradingStrategy


class RiskManagedStrategy(TradingStrategy):
    """
    Conservative, long-only strategy.

    Entry conditions:
    - Current market data.
    - Price above SMA20.
    - SMA20 above SMA50.
    - Positive 20-day momentum.
    - Annualized 20-day volatility below the configured maximum.

    Exit conditions:
    - Price falls below SMA20.
    - SMA20 falls below SMA50.
    - Annualized 20-day volatility exceeds the configured maximum.

    Capital controls:
    - Uses a conservative fraction of current portfolio equity.
    - Limits each new position to a fraction of current equity.
    - Maximum allocation per stock: 33% of portfolio equity.
    - Maximum total invested exposure: 95% of portfolio equity.
    - Reserves a buying-power buffer.
    - Buys whole shares only.

    The strategy does not submit or execute orders.
    """

    strategy_type = "risk_managed"

    DEFAULT_ALLOCATION_FRACTION = 0.50
    DEFAULT_MAX_POSITION_FRACTION = 0.10
    DEFAULT_MAX_VOLATILITY = 0.40
    DEFAULT_MAX_NEW_POSITIONS = 5
    DEFAULT_MIN_MOMENTUM = 0.0

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

        max_position_fraction = float(
            config.get(
                "max_position_fraction",
                self.DEFAULT_MAX_POSITION_FRACTION,
            )
        )

        max_volatility = float(
            config.get(
                "max_volatility",
                self.DEFAULT_MAX_VOLATILITY,
            )
        )

        min_momentum = float(
            config.get(
                "min_momentum",
                self.DEFAULT_MIN_MOMENTUM,
            )
        )

        max_new_positions = config.get(
            "max_new_positions",
            self.DEFAULT_MAX_NEW_POSITIONS,
        )

        if (
            not isfinite(allocation_fraction)
            or not 0 < allocation_fraction <= 1
        ):
            raise ValueError(
                "allocation_fraction must be greater than 0 "
                "and no greater than 1."
            )

        if (
            not isfinite(max_position_fraction)
            or not 0 < max_position_fraction <= 1
        ):
            raise ValueError(
                "max_position_fraction must be greater than 0 "
                "and no greater than 1."
            )

        if not isfinite(max_volatility) or max_volatility <= 0:
            raise ValueError(
                "max_volatility must be a finite positive number."
            )

        if not isfinite(min_momentum):
            raise ValueError("min_momentum must be finite.")

        if (
            isinstance(max_new_positions, bool)
            or not isinstance(max_new_positions, int)
            or max_new_positions <= 0
        ):
            raise ValueError(
                "max_new_positions must be a positive integer."
            )

        holdings = {
            holding["symbol"].upper(): holding
            for holding in portfolio["holdings"]
            if holding["quantity"] > 0
        }

        stock_by_symbol = {
            stock["symbol"].upper(): stock
            for stock in universe["stocks"]
        }

        decisions = []
        existing_market_value = 0.0
        market_value_to_sell = 0.0

        # --------------------------------------------------
        # 1. Value existing holdings and evaluate exit signals.
        # --------------------------------------------------

        for symbol, holding in holdings.items():

            stock = stock_by_symbol.get(symbol)

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
                        "using current market data. No decisions generated."
                    ),
                    decisions=[],
                )

            latest_price = float(stock["latest_price"])
            quantity = int(holding["quantity"])

            holding_market_value = latest_price * quantity
            existing_market_value += holding_market_value

            indicators = stock.get("indicators") or {}

            sma_20 = indicators.get("sma_20")
            sma_50 = indicators.get("sma_50")
            volatility = indicators.get("volatility_20d")

            if any(
                value is None
                for value in (sma_20, sma_50, volatility)
            ):
                continue

            sma_20 = float(sma_20)
            sma_50 = float(sma_50)
            volatility = float(volatility)

            if not all(
                isfinite(value)
                for value in (latest_price, sma_20, sma_50, volatility)
            ):
                continue

            if sma_20 <= 0 or sma_50 <= 0 or volatility < 0:
                continue

            exit_reasons = []

            if latest_price < sma_20:
                exit_reasons.append("price fell below SMA20")

            if sma_20 < sma_50:
                exit_reasons.append("SMA20 fell below SMA50")

            if volatility > max_volatility:
                exit_reasons.append(
                    f"annualized 20-day volatility reached "
                    f"{volatility:.2%}, exceeding the "
                    f"{max_volatility:.2%} limit"
                )

            if not exit_reasons:
                continue

            decisions.append(
                AgentTradeDecision(
                    symbol=symbol,
                    action="sell",
                    quantity=quantity,
                    confidence=0.95,
                    rationale=(
                        "Guardian risk exit triggered: "
                        + "; ".join(exit_reasons)
                        + ". Selling the entire existing position."
                    ),
                )
            )

            market_value_to_sell += holding_market_value

        # --------------------------------------------------
        # 2. Calculate portfolio exposure after planned sells.
        # --------------------------------------------------

        portfolio_equity = available_cash + existing_market_value

        if portfolio_equity <= 0:
            return AgentDecision(
                as_of_date=as_of_date,
                summary="Portfolio equity is insufficient for trading.",
                decisions=decisions,
            )

        projected_existing_market_value = (
            existing_market_value - market_value_to_sell
        )

        maximum_total_exposure = (
            portfolio_equity * self.MAX_TOTAL_INVESTED_EXPOSURE
        )

        remaining_exposure = max(
            0.0,
            maximum_total_exposure - projected_existing_market_value,
        )

        maximum_single_stock_value = (
            portfolio_equity * self.MAX_SINGLE_STOCK_ALLOCATION
        )

        # --------------------------------------------------
        # 3. Evaluate new BUY opportunities.
        # --------------------------------------------------

        if available_cash <= 0:
            return AgentDecision(
                as_of_date=as_of_date,
                summary=(
                    f"Generated {len(decisions)} sell decisions. "
                    "No available cash for new risk-managed investments."
                ),
                decisions=decisions,
            )

        existing_holdings = set(holdings.keys())

        candidates = []

        for stock in universe["stocks"]:

            symbol = stock["symbol"].upper()

            if symbol in existing_holdings:
                continue

            if stock.get("data_status") != "current":
                continue

            latest_price = stock.get("latest_price")

            if latest_price is None:
                continue

            indicators = stock.get("indicators") or {}

            sma_20 = indicators.get("sma_20")
            sma_50 = indicators.get("sma_50")
            momentum = indicators.get("momentum_20d")
            volatility = indicators.get("volatility_20d")

            if any(
                value is None
                for value in (sma_20, sma_50, momentum, volatility)
            ):
                continue

            latest_price = float(latest_price)
            sma_20 = float(sma_20)
            sma_50 = float(sma_50)
            momentum = float(momentum)
            volatility = float(volatility)

            if not all(
                isfinite(value)
                for value in (
                    latest_price,
                    sma_20,
                    sma_50,
                    momentum,
                    volatility,
                )
            ):
                continue

            if latest_price <= 0 or sma_20 <= 0 or sma_50 <= 0:
                continue

            if volatility < 0:
                continue

            if latest_price <= sma_20:
                continue

            if sma_20 <= sma_50:
                continue

            if momentum <= min_momentum:
                continue

            if volatility > max_volatility:
                continue

            candidates.append(
                {
                    "symbol": symbol,
                    "latest_price": latest_price,
                    "momentum": momentum,
                    "volatility": volatility,
                }
            )

        candidates.sort(
            key=lambda item: (
                item["volatility"],
                item["symbol"],
            )
        )

        selected_candidates = candidates[:max_new_positions]

        if not selected_candidates:
            return AgentDecision(
                as_of_date=as_of_date,
                summary=(
                    f"Generated {len(decisions)} sell decisions. "
                    "No stocks met Guardian's trend and risk conditions."
                ),
                decisions=decisions,
            )

        # Do not count future sell proceeds as available cash.
        # Planned sells can release exposure capacity, but cash is
        # unavailable until those orders actually execute.
        maximum_new_investment = min(
            portfolio_equity * allocation_fraction,
            available_cash / self.ORDER_RESERVATION_BUFFER,
            remaining_exposure / self.ORDER_RESERVATION_BUFFER,
        )

        target_per_stock = (
            maximum_new_investment / len(selected_candidates)
        )

        # Preserve Guardian's more conservative per-position target.
        max_position_budget = min(
            portfolio_equity * max_position_fraction,
            maximum_single_stock_value,
        )

        for candidate in selected_candidates:

            price = candidate["latest_price"]

            position_budget = min(
                target_per_stock,
                max_position_budget,
            )

            reserved_cost_per_share = (
                price * self.ORDER_RESERVATION_BUFFER
            )

            quantity = floor(
                position_budget / reserved_cost_per_share
            )

            if quantity <= 0:
                continue

            volatility = candidate["volatility"]
            momentum = candidate["momentum"]

            confidence = min(
                0.90,
                max(
                    0.60,
                    0.90 - volatility * 0.5,
                ),
            )

            decisions.append(
                AgentTradeDecision(
                    symbol=candidate["symbol"],
                    action="buy",
                    quantity=quantity,
                    confidence=confidence,
                    rationale=(
                        f"Guardian trend and risk conditions passed: "
                        f"price is above SMA20, SMA20 is above SMA50, "
                        f"20-day momentum is {momentum:.2%}, and "
                        f"annualized 20-day volatility is "
                        f"{volatility:.2%}."
                    ),
                )
            )

        buy_count = sum(
            decision.action == "buy"
            for decision in decisions
        )

        sell_count = sum(
            decision.action == "sell"
            for decision in decisions
        )

        return AgentDecision(
            as_of_date=as_of_date,
            summary=(
                f"Generated {sell_count} sell decisions and "
                f"{buy_count} buy decisions after evaluating "
                f"{len(candidates)} eligible low-volatility stocks."
            ),
            decisions=decisions,
        )

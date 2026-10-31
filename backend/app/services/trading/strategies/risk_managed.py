
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

    Candidates are ranked by lowest volatility first.

    Capital controls:
    - Uses a conservative fraction of initial capital.
    - Limits each position to a fraction of initial capital.
    - Reserves a buying-power buffer.
    - Buys whole shares only.
    """

    strategy_type = "risk_managed"

    DEFAULT_ALLOCATION_FRACTION = 0.50
    DEFAULT_MAX_POSITION_FRACTION = 0.10
    DEFAULT_MAX_VOLATILITY = 0.40
    DEFAULT_MAX_NEW_POSITIONS = 5
    DEFAULT_MIN_MOMENTUM = 0.0

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

        if not 0 < allocation_fraction <= 1:
            raise ValueError(
                "allocation_fraction must be greater than 0 "
                "and no greater than 1."
            )

        if not 0 < max_position_fraction <= 1:
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

        if initial_cash <= 0 or available_cash <= 0:
            return AgentDecision(
                as_of_date=as_of_date,
                summary="No available cash for risk-managed investments.",
                decisions=[],
            )

        existing_holdings = {
            holding["symbol"].upper()
            for holding in portfolio["holdings"]
            if holding["quantity"] > 0
        }

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

            # Require a positive trend.
            if latest_price <= sma_20:
                continue

            if sma_20 <= sma_50:
                continue

            if momentum <= min_momentum:
                continue

            # Avoid stocks with excessive historical volatility.
            if volatility > max_volatility:
                continue

            candidates.append({
                "symbol": symbol,
                "latest_price": latest_price,
                "momentum": momentum,
                "volatility": volatility,
            })

        # Prefer the least volatile eligible stocks.
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
                    "No stocks met Guardian's trend and risk conditions."
                ),
                decisions=[],
            )

        total_budget = min(
            initial_cash * allocation_fraction,
            available_cash / self.ORDER_RESERVATION_BUFFER,
        )

        target_per_stock = (
            total_budget / len(selected_candidates)
        )

        max_position_budget = (
            initial_cash * max_position_fraction
        )

        decisions = []

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

        return AgentDecision(
            as_of_date=as_of_date,
            summary=(
                f"Evaluated {len(candidates)} eligible low-volatility "
                f"stocks and generated {len(decisions)} buy decisions."
            ),
            decisions=decisions,
        )

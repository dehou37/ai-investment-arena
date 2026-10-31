
from datetime import date
from math import floor
from typing import Any

from app.schemas.agent_decision import AgentDecision, AgentTradeDecision
from app.services.trading.strategies.base import TradingStrategy


class MeanReversionStrategy(TradingStrategy):
    """
    Contrarian mean-reversion strategy.

    Entry conditions:
    - Current market data.
    - RSI14 below the configured maximum.
    - Negative 20-day momentum.
    - Latest price below SMA20.

    Candidates are ranked by lowest RSI first.

    The strategy:
    - Avoids existing holdings.
    - Uses equal allocation across selected candidates.
    - Buys whole shares only.
    - Respects available buying power.
    - Does not sell or execute orders.
    """

    strategy_type = "mean_reversion"

    DEFAULT_ALLOCATION_FRACTION = 0.95
    ORDER_RESERVATION_BUFFER = 1.05
    DEFAULT_MAX_RSI = 30.0
    DEFAULT_MAX_NEW_POSITIONS = 5

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

        max_rsi = float(
            config.get(
                "max_rsi",
                self.DEFAULT_MAX_RSI,
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

        if not 0 < max_rsi <= 100:
            raise ValueError(
                "max_rsi must be greater than 0 and no greater than 100."
            )

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
                summary="No available cash for mean-reversion investments.",
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

            if latest_price is None or float(latest_price) <= 0:
                continue

            indicators = stock.get("indicators") or {}

            rsi = indicators.get("rsi_14")
            momentum = indicators.get("momentum_20d")
            sma_20 = indicators.get("sma_20")

            if rsi is None or momentum is None or sma_20 is None:
                continue

            rsi = float(rsi)
            momentum = float(momentum)
            sma_20 = float(sma_20)
            latest_price = float(latest_price)

            # Require oversold conditions.
            if not 0 <= rsi < max_rsi:
                continue

            # Require negative recent momentum.
            if momentum >= 0:
                continue

            # Require price below its short-term moving average.
            if latest_price >= sma_20:
                continue

            candidates.append({
                "symbol": symbol,
                "latest_price": latest_price,
                "rsi": rsi,
                "momentum": momentum,
            })

        # Lowest RSI first: most oversold candidates are considered first.
        candidates.sort(
            key=lambda item: (item["rsi"], item["symbol"]),
        )

        selected_candidates = candidates[:max_new_positions]

        if not selected_candidates:
            return AgentDecision(
                as_of_date=as_of_date,
                summary=(
                    "No stocks met the mean-reversion entry conditions."
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

        decisions = []

        for candidate in selected_candidates:

            price = candidate["latest_price"]

            reserved_cost_per_share = (
                price * self.ORDER_RESERVATION_BUFFER
            )

            quantity = floor(
                target_per_stock / reserved_cost_per_share
            )

            if quantity <= 0:
                continue

            rsi = candidate["rsi"]
            momentum = candidate["momentum"]

            confidence = min(
                0.90,
                0.60 + (max_rsi - rsi) / 100,
            )

            decisions.append(
                AgentTradeDecision(
                    symbol=candidate["symbol"],
                    action="buy",
                    quantity=quantity,
                    confidence=confidence,
                    rationale=(
                        f"Potential mean-reversion candidate: "
                        f"RSI14 is {rsi:.2f}, 20-day momentum is "
                        f"{momentum:.2%}, and price is below SMA20. "
                        "The stock meets the configured oversold criteria."
                    ),
                )
            )

        summary = (
            f"Identified {len(candidates)} mean-reversion candidates "
            f"and generated {len(decisions)} buy decisions from the "
            f"lowest-RSI candidates."
        )

        return AgentDecision(
            as_of_date=as_of_date,
            summary=summary,
            decisions=decisions,
        )

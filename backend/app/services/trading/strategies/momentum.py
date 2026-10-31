from datetime import date
from math import floor
from typing import Any

from app.schemas.agent_decision import AgentDecision, AgentTradeDecision
from app.services.trading.strategies.base import TradingStrategy


class MomentumStrategy(TradingStrategy):
    """
    Momentum strategy.

    Exit conditions:
    - 20-day momentum becomes zero or negative.
    - SMA20 falls to or below SMA50.
    - Only sells when market data and required indicators are current.

    Entry conditions:
    - Stock has current market data.
    - 20-day momentum exceeds the configured minimum.
    - SMA20 is above SMA50.

    The strategy:
    - Sells the entire existing position when an exit condition is met.
    - Ranks new candidates by 20-day momentum.
    - Avoids purchasing existing holdings.
    - Uses whole shares only.
    - Respects available buying power.
    - Does not submit or execute orders.
    """

    strategy_type = "momentum"

    DEFAULT_ALLOCATION_FRACTION = 0.95
    ORDER_RESERVATION_BUFFER = 1.05
    DEFAULT_MIN_MOMENTUM = 0.0
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

        if max_new_positions <= 0 or not isinstance(max_new_positions, int):
            raise ValueError(
                "max_new_positions must be a positive integer."
            )

        # Map current holdings by stock symbol.
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
        symbols_to_sell = set()

        # --------------------------------------------------
        # 1. Evaluate existing positions for exit conditions.
        # --------------------------------------------------

        for symbol, holding in holdings.items():

            stock = stock_by_symbol.get(symbol)

            # Never make exit decisions using stale or missing data.
            if stock is None or stock.get("data_status") != "current":
                continue

            indicators = stock.get("indicators") or {}

            momentum = indicators.get("momentum_20d")
            sma_20 = indicators.get("sma_20")
            sma_50 = indicators.get("sma_50")

            if momentum is None or sma_20 is None or sma_50 is None:
                continue

            momentum = float(momentum)
            sma_20 = float(sma_20)
            sma_50 = float(sma_50)

            exit_reasons = []

            if momentum <= 0:
                exit_reasons.append(
                    f"20-day momentum turned negative or neutral "
                    f"({momentum:.2%})"
                )

            if sma_20 <= sma_50:
                exit_reasons.append(
                    "SMA20 fell to or below SMA50"
                )

            if not exit_reasons:
                continue

            quantity = int(holding["quantity"])

            if quantity <= 0:
                continue

            decisions.append(
                AgentTradeDecision(
                    symbol=symbol,
                    action="sell",
                    quantity=quantity,
                    confidence=0.90,
                    rationale=(
                        "Momentum exit condition triggered: "
                        + "; ".join(exit_reasons)
                        + ". Selling the entire existing position."
                    ),
                )
            )

            symbols_to_sell.add(symbol)

        # --------------------------------------------------
        # 2. Evaluate new BUY opportunities.
        # --------------------------------------------------

        if initial_cash <= 0 or available_cash <= 0:
            summary = (
                f"Generated {len(decisions)} sell decisions. "
                "No available cash for new momentum investments."
            )

            return AgentDecision(
                as_of_date=as_of_date,
                summary=summary,
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

            if latest_price is None or float(latest_price) <= 0:
                continue

            indicators = stock.get("indicators") or {}

            momentum = indicators.get("momentum_20d")
            sma_20 = indicators.get("sma_20")
            sma_50 = indicators.get("sma_50")

            if momentum is None or sma_20 is None or sma_50 is None:
                continue

            momentum = float(momentum)
            sma_20 = float(sma_20)
            sma_50 = float(sma_50)

            if momentum <= min_momentum:
                continue

            if sma_20 <= sma_50:
                continue

            candidates.append(
                {
                    "symbol": symbol,
                    "latest_price": float(latest_price),
                    "momentum": momentum,
                }
            )

        # Strongest positive momentum first.
        candidates.sort(
            key=lambda item: item["momentum"],
            reverse=True,
        )

        selected_candidates = candidates[:max_new_positions]

        if not selected_candidates:
            summary = (
                f"Generated {len(decisions)} sell decisions. "
                "No new stocks met the momentum entry conditions."
            )

            return AgentDecision(
                as_of_date=as_of_date,
                summary=summary,
                decisions=decisions,
            )

        total_budget = min(
            initial_cash * allocation_fraction,
            available_cash / self.ORDER_RESERVATION_BUFFER,
        )

        target_per_stock = total_budget / len(selected_candidates)

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

            momentum = candidate["momentum"]

            confidence = min(
                0.95,
                0.60 + momentum * 2,
            )

            decisions.append(
                AgentTradeDecision(
                    symbol=candidate["symbol"],
                    action="buy",
                    quantity=quantity,
                    confidence=confidence,
                    rationale=(
                        f"Positive 20-day momentum of "
                        f"{momentum:.2%}, with SMA20 above SMA50. "
                        "Selected as a strong upward-trend candidate."
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

        summary = (
            f"Generated {sell_count} sell decisions and "
            f"{buy_count} buy decisions. "
            f"Identified {len(candidates)} qualifying momentum "
            "candidates and selected the strongest candidates."
        )

        return AgentDecision(
            as_of_date=as_of_date,
            summary=summary,
            decisions=decisions,
        )
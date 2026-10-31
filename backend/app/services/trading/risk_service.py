
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.agent_decision import AgentDecision


MAX_SINGLE_STOCK_ALLOCATION = Decimal("0.20")
MAX_TOTAL_INVESTED_EXPOSURE = Decimal("0.95")


class RiskValidationError(Exception):
    """Raised when an agent decision violates portfolio risk limits."""


def _to_decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise RiskValidationError(
            f"Invalid numeric value for {field_name}."
        )

    if not result.is_finite():
        raise RiskValidationError(
            f"Non-finite numeric value for {field_name}."
        )

    return result


def validate_agent_decision(
    decision: AgentDecision,
    context: dict[str, Any],
) -> None:
    """
    Validate an agent's complete proposed decision against global
    portfolio risk limits.

    Raises RiskValidationError if any proposed trade is invalid.

    This service does not create orders or modify the database.
    Brokerage validation remains responsible for final buying-power
    and available-share checks.
    """

    # -----------------------------------------------------
    # 1. Validate context structure
    # -----------------------------------------------------

    if not isinstance(context, dict):
        raise RiskValidationError("Market context must be a dictionary.")

    portfolio = context.get("portfolio")

    if not isinstance(portfolio, dict):
        raise RiskValidationError("Portfolio context is missing or invalid.")

    universe = context.get("universe")

    if not isinstance(universe, dict):
        raise RiskValidationError("Stock universe context is missing or invalid.")

    stocks = universe.get("stocks")

    if not isinstance(stocks, list):
        raise RiskValidationError("Stock universe list is invalid.")

    holdings = portfolio.get("holdings")

    if not isinstance(holdings, list):
        raise RiskValidationError("Portfolio holdings are invalid.")

    # -----------------------------------------------------
    # 2. Validate decision date
    # -----------------------------------------------------

    context_date = context.get("as_of_date")

    if str(decision.as_of_date) != str(context_date):
        raise RiskValidationError(
            "Decision date does not match market context date."
        )

    # -----------------------------------------------------
    # 3. Validate trading constraints
    # -----------------------------------------------------

    constraints = context.get("trading_constraints")

    if not isinstance(constraints, dict):
        raise RiskValidationError("Trading constraints are missing.")

    if constraints.get("long_only") is not True:
        raise RiskValidationError("Long-only trading must be enabled.")

    if constraints.get("whole_shares_only") is not True:
        raise RiskValidationError("Whole-share trading must be enabled.")

    if constraints.get("margin_allowed") is not False:
        raise RiskValidationError("Margin trading must be disabled.")

    if constraints.get("short_selling_allowed") is not False:
        raise RiskValidationError("Short selling must be disabled.")

    if constraints.get("fractional_shares_allowed") is not False:
        raise RiskValidationError("Fractional shares must be disabled.")

    # -----------------------------------------------------
    # 4. Build stock universe and price lookup
    # -----------------------------------------------------

    stock_prices: dict[str, Decimal] = {}

    for stock in stocks:
        if not isinstance(stock, dict):
            raise RiskValidationError("Invalid stock entry in universe.")

        symbol = stock.get("symbol")

        if not isinstance(symbol, str) or not symbol.strip():
            raise RiskValidationError("Invalid stock symbol in universe.")

        symbol = symbol.strip().upper()

        if symbol in stock_prices:
            raise RiskValidationError(
                f"Duplicate stock symbol in universe: {symbol}."
            )

        if stock.get("data_status") != "current":
            stock_prices[symbol] = Decimal("0")
            continue

        price = _to_decimal(
            stock.get("latest_price"),
            f"{symbol} latest price",
        )

        if price <= 0:
            raise RiskValidationError(
                f"{symbol} has no usable current market price."
            )

        stock_prices[symbol] = price

    # -----------------------------------------------------
    # 5. Validate existing holdings and calculate equity
    # -----------------------------------------------------

    cash_balance = _to_decimal(
        portfolio.get("cash_balance"),
        "cash balance",
    )

    if cash_balance < 0:
        raise RiskValidationError("Portfolio cash cannot be negative.")

    projected_quantities: dict[str, int] = {}
    current_market_values: dict[str, Decimal] = {}

    for holding in holdings:
        if not isinstance(holding, dict):
            raise RiskValidationError("Invalid portfolio holding.")

        symbol = holding.get("symbol")

        if not isinstance(symbol, str) or not symbol.strip():
            raise RiskValidationError("Invalid symbol in portfolio holding.")

        symbol = symbol.strip().upper()

        quantity = holding.get("quantity")

        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise RiskValidationError(
                f"Invalid holding quantity for {symbol}."
            )

        if symbol not in stock_prices:
            raise RiskValidationError(
                f"Cannot value existing holding {symbol}: "
                "it is missing from the competition universe."
            )

        price = stock_prices[symbol]

        if price <= 0:
            raise RiskValidationError(
                f"Cannot calculate portfolio exposure: "
                f"{symbol} market data is stale or missing."
            )

        projected_quantities[symbol] = quantity
        current_market_values[symbol] = price * quantity

    current_market_value = sum(
        current_market_values.values(),
        Decimal("0"),
    )

    portfolio_equity = cash_balance + current_market_value

    if portfolio_equity <= 0:
        raise RiskValidationError(
            "Portfolio equity must be positive."
        )

    # -----------------------------------------------------
    # 6. Validate proposed trades and project holdings
    # -----------------------------------------------------

    decisions_by_symbol = {
        item.symbol.upper(): item
        for item in decision.decisions
    }

    for symbol, trade in decisions_by_symbol.items():

        if trade.action == "hold":
            continue

        if symbol not in stock_prices:
            raise RiskValidationError(
                f"{symbol} is not in the competition's frozen stock universe."
            )

        if stock_prices[symbol] <= 0:
            raise RiskValidationError(
                f"{symbol} has stale or missing market data. "
                "BUY and SELL decisions are not allowed."
            )

        if trade.quantity is None:
            raise RiskValidationError(
                f"{symbol} trade is missing a quantity."
            )

        if (
            isinstance(trade.quantity, bool)
            or not isinstance(trade.quantity, int)
            or trade.quantity <= 0
        ):
            raise RiskValidationError(
                f"{symbol} trade quantity must be a positive whole number."
            )

    # Process SELLs first so that proceeds and released exposure
    # are reflected before evaluating the proposed BUYs.
    for symbol, trade in decisions_by_symbol.items():

        if trade.action != "sell":
            continue

        owned_quantity = projected_quantities.get(symbol, 0)

        if trade.quantity > owned_quantity:
            raise RiskValidationError(
                f"Cannot sell {trade.quantity} shares of {symbol}; "
                f"only {owned_quantity} shares are held."
            )

        projected_quantities[symbol] = (
            owned_quantity - trade.quantity
        )

    # Apply all BUYs to the projected holdings.
    for symbol, trade in decisions_by_symbol.items():

        if trade.action != "buy":
            continue

        current_quantity = projected_quantities.get(symbol, 0)

        projected_quantities[symbol] = (
            current_quantity + trade.quantity
        )

    # -----------------------------------------------------
    # 7. Calculate projected exposure
    # -----------------------------------------------------

    projected_values: dict[str, Decimal] = {}

    for symbol, quantity in projected_quantities.items():

        if quantity == 0:
            continue

        projected_values[symbol] = (
            stock_prices[symbol] * quantity
        )

    projected_total_exposure = sum(
        projected_values.values(),
        Decimal("0"),
    )

    # -----------------------------------------------------
    # 8. Enforce maximum single-stock allocation
    # -----------------------------------------------------

    maximum_single_stock_value = (
        portfolio_equity * MAX_SINGLE_STOCK_ALLOCATION
    )

    for symbol, market_value in projected_values.items():

        if market_value > maximum_single_stock_value:
            allocation_pct = (
                market_value / portfolio_equity * Decimal("100")
            )

            raise RiskValidationError(
                f"{symbol} would represent "
                f"{allocation_pct:.2f}% of portfolio equity. "
                f"The maximum allowed allocation is "
                f"{MAX_SINGLE_STOCK_ALLOCATION * 100}%."
            )

    # -----------------------------------------------------
    # 9. Enforce maximum total invested exposure
    # -----------------------------------------------------

    maximum_total_exposure = (
        portfolio_equity * MAX_TOTAL_INVESTED_EXPOSURE
    )

    if projected_total_exposure > maximum_total_exposure:

        exposure_pct = (
            projected_total_exposure
            / portfolio_equity
            * Decimal("100")
        )

        raise RiskValidationError(
            f"Total invested exposure would be "
            f"{exposure_pct:.2f}% of portfolio equity. "
            f"The maximum allowed is "
            f"{MAX_TOTAL_INVESTED_EXPOSURE * 100}%."
        )

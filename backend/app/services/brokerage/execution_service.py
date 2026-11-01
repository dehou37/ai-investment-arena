
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Agent,
    Competition,
    Execution,
    Order,
    Portfolio,
    Position,
    StockBar,
)

from app.services.brokerage.execution_config import (
    DAILY_TIMEFRAME,
    MARKET_SLIPPAGE_RATE,
    TRADING_FEE_RATE,
)

from app.services.trading.calendar_service import (
    get_market_session_close,
    get_next_market_open,
)
from app.core.config import settings

def get_session_bar(
    db: Session,
    order: Order,
):
    """
    Find the daily bar corresponding to the order's
    scheduled execution session, using the configured
    Alpaca data source.
    """

    session_date = order.scheduled_execution_at.date()

    return db.scalar(
        select(StockBar)
        .where(
            StockBar.stock_id == order.stock_id,
            StockBar.timeframe == settings.ALPACA_TIMEFRAME,
            StockBar.provider == settings.ALPACA_PROVIDER,
            StockBar.feed == settings.ALPACA_FEED,
            StockBar.adjustment == settings.ALPACA_ADJUSTMENT,
            func.date(StockBar.timestamp) == session_date,
        )
        .order_by(StockBar.timestamp.desc())
        .limit(1)
    )

def calculate_fill_price(
    order: Order,
    bar: StockBar,
):
    """
    Calculate the simulated execution price.

    Market orders:
        Buy: opening price + slippage.
        Sell: opening price - slippage.

    Limit orders:
        Buy: fill at open if open <= limit;
             otherwise fill at limit if low <= limit.

        Sell: fill at open if open >= limit;
              otherwise fill at limit if high >= limit.

    Returns:
        execution_price
        reference_price
        slippage_cost

    Returns None for execution_price if a limit order
    was not reached during the session.
    """

    market_open = Decimal(str(bar.open))
    market_high = Decimal(str(bar.high))
    market_low = Decimal(str(bar.low))

    # -----------------------------------------------------
    # Market orders
    # -----------------------------------------------------

    if order.order_type == "market":

        if order.side == "buy":

            execution_price = (
                market_open
                * (Decimal("1") + MARKET_SLIPPAGE_RATE)
            )

            slippage_cost = (
                execution_price - market_open
            ) * order.quantity

        else:

            execution_price = (
                market_open
                * (Decimal("1") - MARKET_SLIPPAGE_RATE)
            )

            slippage_cost = (
                market_open - execution_price
            ) * order.quantity

        return (
            execution_price,
            market_open,
            slippage_cost,
        )

    # -----------------------------------------------------
    # Limit orders
    # -----------------------------------------------------

    limit_price = Decimal(str(order.limit_price))

    if order.side == "buy":

        if market_open <= limit_price:
            execution_price = market_open

        elif market_low <= limit_price:
            execution_price = limit_price

        else:
            return None, market_open, Decimal("0")

    else:

        if market_open >= limit_price:
            execution_price = market_open

        elif market_high >= limit_price:
            execution_price = limit_price

        else:
            return None, market_open, Decimal("0")

    return (
        execution_price,
        market_open,
        Decimal("0"),
    )


def execute_buy_order(
    db: Session,
    order: Order,
    portfolio: Portfolio,
    execution_price: Decimal,
    slippage_cost: Decimal,
):
    """
    Execute a buy order and update cash and holdings.
    """

    quantity = order.quantity

    gross_cost = execution_price * quantity
    fees = gross_cost * TRADING_FEE_RATE
    total_cost = gross_cost + fees

    cash_balance = Decimal(str(portfolio.cash_balance))

    # Recheck available cash against actual execution cost.
    if total_cost > cash_balance:

        order.status = "rejected"

        return None

    position = db.scalar(
        select(Position)
        .where(
            Position.portfolio_id == portfolio.id,
            Position.stock_id == order.stock_id,
        )
        .with_for_update()
    )

    if position is None:

        position = Position(
            portfolio_id=portfolio.id,
            stock_id=order.stock_id,
            quantity=quantity,
            average_entry_price=execution_price,
        )

        db.add(position)

    else:

        old_quantity = position.quantity

        old_cost = (
            Decimal(str(position.average_entry_price))
            * old_quantity
        )

        new_cost = execution_price * quantity

        new_quantity = old_quantity + quantity

        position.average_entry_price = (
            old_cost + new_cost
        ) / new_quantity

        position.quantity = new_quantity

    portfolio.cash_balance = cash_balance - total_cost

    return Execution(
        order_id=order.id,
        quantity=quantity,
        execution_price=execution_price,
        fees=fees,
        slippage=slippage_cost,
        executed_at=datetime.now(timezone.utc),
    )


def execute_sell_order(
    db: Session,
    order: Order,
    portfolio: Portfolio,
    execution_price: Decimal,
    slippage_cost: Decimal,
):
    """
    Execute a sell order and update cash and holdings.
    """

    position = db.scalar(
        select(Position)
        .where(
            Position.portfolio_id == portfolio.id,
            Position.stock_id == order.stock_id,
        )
        .with_for_update()
    )

    if position is None or position.quantity < order.quantity:

        order.status = "rejected"

        return None

    quantity = order.quantity

    gross_proceeds = execution_price * quantity
    fees = gross_proceeds * TRADING_FEE_RATE

    net_proceeds = gross_proceeds - fees

    cash_balance = Decimal(str(portfolio.cash_balance))

    portfolio.cash_balance = cash_balance + net_proceeds

    position.quantity -= quantity

    if position.quantity == 0:
        db.delete(position)

    return Execution(
        order_id=order.id,
        quantity=quantity,
        execution_price=execution_price,
        fees=fees,
        slippage=slippage_cost,
        executed_at=datetime.now(timezone.utc),
    )


def execute_queued_orders(
    db: Session,
    competition_id: UUID,
) -> list[Order]:
    """
    Execute eligible queued orders belonging to a competition.

    Execution rules:

    1. Competition must be active.
    2. Order must be queued.
    3. Scheduled execution session must have completed.
    4. A matching completed daily stock bar must exist.
    5. Market orders execute at the session open with slippage.
    6. Limit orders execute only when their limit is reached.
    7. Unfilled limit orders are rescheduled to the next session.
    8. Portfolio cash and positions are updated.
    9. Every successful fill creates an Execution record.

    Orders without available completed daily data remain queued.
    """

    # -----------------------------------------------------
    # 1. Verify competition
    # -----------------------------------------------------

    competition = db.scalar(
        select(Competition).where(
            Competition.id == competition_id
        )
    )

    if competition is None:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Competition not found.",
        )

    if competition.status != "active":

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only active competitions can execute orders.",
        )

    now = datetime.now(timezone.utc)

    # -----------------------------------------------------
    # 2. Retrieve queued orders for this competition only
    # -----------------------------------------------------

    queued_orders = db.scalars(
        select(Order)
        .join(
            Portfolio,
            Order.portfolio_id == Portfolio.id,
        )
        .join(
            Agent,
            Portfolio.agent_id == Agent.id,
        )
        .where(
            Agent.competition_id == competition_id,
            Order.status == "queued",
            Order.scheduled_execution_at <= now,
        )
        .order_by(
            Order.scheduled_execution_at.asc(),
            Order.submitted_at.asc(),
        )
        .with_for_update()
    ).all()

    processed_orders = []

    try:

        for order in queued_orders:

            # -------------------------------------------------
            # 3. Lock portfolio
            # -------------------------------------------------

            portfolio = db.scalar(
                select(Portfolio)
                .where(
                    Portfolio.id == order.portfolio_id
                )
                .with_for_update()
            )

            if portfolio is None:
                continue

            # -------------------------------------------------
            # 4. Verify market session has completed
            # -------------------------------------------------

            session_date = (
                order.scheduled_execution_at.date()
            )

            session_close = get_market_session_close(
                session_date
            )

            if session_close is None:
                continue

            if now < session_close:
                continue

            # -------------------------------------------------
            # 5. Retrieve daily market data
            # -------------------------------------------------

            bar = get_session_bar(
                db,
                order,
            )

            if bar is None:
                continue

            # -------------------------------------------------
            # 6. Calculate execution price
            # -------------------------------------------------

            (
                execution_price,
                reference_price,
                slippage_cost,
            ) = calculate_fill_price(
                order,
                bar,
            )

            # -------------------------------------------------
            # 7. Handle unfilled limit orders
            # -------------------------------------------------

            if execution_price is None:

                order.scheduled_execution_at = (
                    get_next_market_open(now)
                )

                processed_orders.append(order)

                continue

            # -------------------------------------------------
            # 8. Execute buy or sell
            # -------------------------------------------------

            if order.side == "buy":

                execution = execute_buy_order(
                    db=db,
                    order=order,
                    portfolio=portfolio,
                    execution_price=execution_price,
                    slippage_cost=slippage_cost,
                )

            else:

                execution = execute_sell_order(
                    db=db,
                    order=order,
                    portfolio=portfolio,
                    execution_price=execution_price,
                    slippage_cost=slippage_cost,
                )

            # -------------------------------------------------
            # 9. Record successful execution
            # -------------------------------------------------

            if execution is None:

                processed_orders.append(order)

                continue

            db.add(execution)

            order.status = "filled"

            processed_orders.append(order)

        # -----------------------------------------------------
        # 10. Commit all updates
        # -----------------------------------------------------

        db.commit()

        for order in processed_orders:
            db.refresh(order)

        return processed_orders

    except Exception:

        db.rollback()

        raise

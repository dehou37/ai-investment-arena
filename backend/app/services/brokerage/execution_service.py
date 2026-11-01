
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Agent,
    Competition,
    Execution,
    MarketSessionMonitor,
    Order,
    Portfolio,
    Position,
    StockBar,
)



from app.services.brokerage.execution_config import (
    MARKET_SLIPPAGE_RATE,
    TRADING_FEE_RATE,
)

from app.services.trading.calendar_service import (
    get_market_session_close,
    get_next_market_open,
)

from app.core.config import settings

from app.services.trading.calendar_service import (
    get_market_session_open,
    get_market_session_close,
    get_next_market_open,
)
from app.services.trading.market_session_monitor_service import (
    MAX_HEARTBEAT_GAP,
    EXECUTION_GRACE_PERIOD,
)

NEW_YORK = ZoneInfo("America/New_York")


def _as_utc(value: datetime) -> datetime:
    """Treat naive timestamps as UTC and normalize aware timestamps."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def validate_session_execution_eligibility(
    db: Session,
    session_date,
    now: datetime,
) -> tuple[bool, str | None]:
    """
    Verify that the application monitored the NYSE session
    continuously enough to permit execution.
    """

    monitor = db.scalar(
        select(MarketSessionMonitor)
        .where(
            MarketSessionMonitor.session_date == session_date
        )
        .with_for_update()
    )

    # No pre-market registration means no historical execution.
    if monitor is None:
        return False, "No pre-market monitoring record exists."

    if monitor.status != "monitoring":
        return False, (
            f"Session monitoring status is '{monitor.status}'."
        )

    session_open = get_market_session_open(session_date)
    session_close = get_market_session_close(session_date)

    if session_open is None or session_close is None:
        return False, "NYSE session boundaries are unavailable."

    session_open = _as_utc(session_open)
    session_close = _as_utc(session_close)

    observed_at = _as_utc(monitor.observed_at)
    last_heartbeat = _as_utc(monitor.last_heartbeat_at)

    if observed_at > session_open:
        return False, "Monitoring did not begin before market open."

    heartbeat_gap = now - last_heartbeat

    if heartbeat_gap < timedelta(0):
        return False, "System clock moved backwards."

    if heartbeat_gap > MAX_HEARTBEAT_GAP:
        return False, "Heartbeat interruption exceeded the permitted gap."

    if now > session_close + EXECUTION_GRACE_PERIOD:
        return False, "Execution deadline has passed."

    return True, None


def get_order_session_date(order: Order):
    """
    Get the NYSE trading date associated with an order's
    scheduled execution timestamp.
    """

    scheduled_at = _as_utc(order.scheduled_execution_at)

    return scheduled_at.astimezone(NEW_YORK).date()


def get_session_bar(
    db: Session,
    order: Order,
):
    """
    Find the daily bar corresponding to the order's
    scheduled NYSE execution session.
    """

    session_date = get_order_session_date(order)

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
    """Execute a buy order and update cash and holdings."""

    quantity = order.quantity

    gross_cost = execution_price * quantity
    fees = gross_cost * TRADING_FEE_RATE
    total_cost = gross_cost + fees

    cash_balance = Decimal(str(portfolio.cash_balance))

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
    """Execute a sell order and update cash and holdings."""

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

    Missed-session protection:
        Orders scheduled for an earlier NYSE date are rescheduled
        to the next eligible market open. They are never filled
        using the missed session's historical daily bar.

    Current-session orders:
        Execute only after the NYSE session closes and matching
        completed daily market data is available.

    Other rules:
        - Competition must be active.
        - Orders must be queued and eligible.
        - Market orders execute at the session open with slippage.
        - Limit orders execute only when their limit is reached.
        - Unfilled limit orders are rescheduled.
        - Successful fills create Execution records.
        - Missing daily data leaves orders queued.
    """

    # 1. Verify competition.

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
    current_ny_date = now.astimezone(NEW_YORK).date()

    # 2. Retrieve queued orders for this competition.

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

            # 3. Lock portfolio.

            portfolio = db.scalar(
                select(Portfolio)
                .where(
                    Portfolio.id == order.portfolio_id
                )
                .with_for_update()
            )

            if portfolio is None:
                continue

            # 4. Determine the scheduled NYSE session date.

            session_date = get_order_session_date(order)

            # 5. Protect against missed historical sessions.
            #
            # Never fill an order using a daily bar from a
            # previous NYSE session.

            if session_date < current_ny_date:

                order.scheduled_execution_at = (
                    get_next_market_open(now)
                )

                processed_orders.append(order)

                continue

            # Do not execute an order scheduled for a future
            # NYSE session.

            if session_date > current_ny_date:
                continue

            # 6. Verify the current market session has closed.

            session_close = get_market_session_close(
                session_date
            )

            if session_close is None:
                continue

            session_close = _as_utc(session_close)

            if now < session_close:
                continue

            # 7. Verify the session was monitored before
            # market open and that heartbeat continuity
            # is still within the permitted limit.

            eligible, reason = validate_session_execution_eligibility(
                db=db,
                session_date=session_date,
                now=now,
            )

            if not eligible:
                order.scheduled_execution_at = (
                    get_next_market_open(now)
                )

                processed_orders.append(order)

                continue

            # 8. Retrieve the daily market bar.

            bar = get_session_bar(
                db=db,
                order=order,
            )

            if bar is None:
                continue

            # 8. Calculate execution price.

            (
                execution_price,
                reference_price,
                slippage_cost,
            ) = calculate_fill_price(
                order=order,
                bar=bar,
            )

            # 9. Reschedule an unfilled limit order.

            if execution_price is None:

                order.scheduled_execution_at = (
                    get_next_market_open(now)
                )

                processed_orders.append(order)

                continue

            # 10. Execute buy or sell.

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

            # 11. Record successful execution or rejection.

            if execution is None:
                processed_orders.append(order)
                continue

            db.add(execution)

            order.status = "filled"

            processed_orders.append(order)

        # 12. Commit all updates.

        db.commit()

        for order in processed_orders:
            db.refresh(order)

        return processed_orders

    except Exception:
        db.rollback()
        raise

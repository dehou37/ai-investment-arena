
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Agent,
    Competition,
    Execution,
    Order,
    Portfolio,
    Position,
    Stock,
    StockBar,
)


MARKET_ORDER_BUFFER = Decimal("1.05")

OPEN_ORDER_STATUSES = [
    "pending",
    "queued",
    "partially_filled",
]


def get_latest_close(
    db: Session,
    stock_id,
) -> Decimal:
    """
    Get the most recent stored raw closing price.

    This is an estimate for order validation only.
    It is NOT the eventual execution price.
    """

    latest_bar = db.scalar(
        select(StockBar)
        .where(StockBar.stock_id == stock_id)
        .order_by(StockBar.timestamp.desc())
        .limit(1)
    )

    if latest_bar is None or latest_bar.close <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No usable historical price is available for this stock.",
        )

    return Decimal(str(latest_bar.close))


def get_remaining_order_quantity(order: Order) -> int:
    """
    Calculate the unfilled quantity of an existing order.
    """

    filled_quantity = sum(
        execution.quantity
        for execution in order.executions
    )

    return max(order.quantity - filled_quantity, 0)


def get_reserved_buying_power(
    db: Session,
    portfolio_id,
) -> Decimal:
    """
    Estimate cash committed to outstanding buy orders.

    Limit orders reserve their limit price.
    Market orders reserve the latest close plus a 5% buffer.

    The buffer is provisional and will be reviewed when
    the execution and fee model is implemented.
    """

    pending_orders = db.scalars(
        select(Order)
        .options(selectinload(Order.executions))
        .where(
            Order.portfolio_id == portfolio_id,
            Order.side == "buy",
            Order.status.in_(OPEN_ORDER_STATUSES),
        )
    ).all()

    reserved_cash = Decimal("0")

    for order in pending_orders:
        remaining_quantity = get_remaining_order_quantity(order)

        if remaining_quantity == 0:
            continue

        if order.order_type == "limit":
            estimated_price = Decimal(str(order.limit_price))
        else:
            latest_close = get_latest_close(
                db,
                order.stock_id,
            )
            estimated_price = latest_close * MARKET_ORDER_BUFFER

        reserved_cash += (
            estimated_price * remaining_quantity
        )

    return reserved_cash


def get_reserved_sell_quantity(
    db: Session,
    portfolio_id,
    stock_id,
) -> int:
    """
    Calculate shares already committed to outstanding sell orders.
    """

    pending_orders = db.scalars(
        select(Order)
        .options(selectinload(Order.executions))
        .where(
            Order.portfolio_id == portfolio_id,
            Order.stock_id == stock_id,
            Order.side == "sell",
            Order.status.in_(OPEN_ORDER_STATUSES),
        )
    ).all()

    reserved_quantity = sum(
        get_remaining_order_quantity(order)
        for order in pending_orders
    )

    return reserved_quantity


def submit_order(
    db: Session,
    competition_id,
    agent_id,
    order_data,
) -> Order:
    """
    Validate and submit a virtual brokerage order.

    Orders are stored as pending. They are not executed here.
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
            detail="Orders can only be submitted to active competitions.",
        )

    # -----------------------------------------------------
    # 2. Verify agent
    # -----------------------------------------------------

    agent = db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.competition_id == competition_id,
        )
    )

    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found in this competition.",
        )

    if agent.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This agent is not active.",
        )

    # -----------------------------------------------------
    # 3. Verify stock
    # -----------------------------------------------------

    stock = db.scalar(
        select(Stock).where(
            Stock.symbol == order_data.stock_symbol,
            Stock.is_active.is_(True),
            Stock.asset_type == "stock",
        )
    )

    if stock is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found or is not tradable.",
        )

    # -----------------------------------------------------
    # 4. Lock portfolio to serialize order submissions
    # -----------------------------------------------------

    portfolio = db.scalar(
        select(Portfolio)
        .where(Portfolio.agent_id == agent.id)
        .with_for_update()
    )

    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent does not have a virtual portfolio.",
        )

    # -----------------------------------------------------
    # 5. Validate buy order
    # -----------------------------------------------------

    if order_data.side == "buy":

        if order_data.order_type == "limit":
            estimated_price = Decimal(
                str(order_data.limit_price)
            )
        else:
            latest_close = get_latest_close(
                db,
                stock.id,
            )

            estimated_price = (
                latest_close * MARKET_ORDER_BUFFER
            )

        new_order_estimate = (
            estimated_price * order_data.quantity
        )

        reserved_cash = get_reserved_buying_power(
            db,
            portfolio.id,
        )

        available_cash = (
            Decimal(str(portfolio.cash_balance))
            - reserved_cash
        )

        if new_order_estimate > available_cash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Insufficient available cash.",
                    "cash_balance": str(portfolio.cash_balance),
                    "reserved_cash": str(reserved_cash),
                    "available_cash": str(available_cash),
                    "estimated_order_cost": str(new_order_estimate),
                },
            )

    # -----------------------------------------------------
    # 6. Validate sell order
    # -----------------------------------------------------

    elif order_data.side == "sell":

        position = db.scalar(
            select(Position)
            .where(
                Position.portfolio_id == portfolio.id,
                Position.stock_id == stock.id,
            )
            .with_for_update()
        )

        if position is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You do not own any shares of this stock.",
            )

        reserved_quantity = get_reserved_sell_quantity(
            db,
            portfolio.id,
            stock.id,
        )

        available_quantity = (
            position.quantity - reserved_quantity
        )

        if order_data.quantity > available_quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Insufficient available shares.",
                    "owned_quantity": position.quantity,
                    "reserved_quantity": reserved_quantity,
                    "available_quantity": available_quantity,
                    "requested_quantity": order_data.quantity,
                },
            )

    # -----------------------------------------------------
    # 7. Create pending order
    # -----------------------------------------------------

    order = Order(
        portfolio_id=portfolio.id,
        stock_id=stock.id,
        side=order_data.side,
        order_type=order_data.order_type,
        quantity=order_data.quantity,
        limit_price=order_data.limit_price,
        status="pending",
    )

    try:
        db.add(order)
        db.commit()
        db.refresh(order)

    except Exception:
        db.rollback()
        raise

    return order

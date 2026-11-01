
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models import (
    Agent,
    Competition,
    Order,
    Portfolio,
    Position,
    Stock,
    StockBar,
)
from app.services.brokerage.execution_config import TRADING_FEE_RATE


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
    Get the most recent stored raw Alpaca closing price
    using the configured feed and timeframe.
    """

    latest_bar = db.scalar(
        select(StockBar)
        .where(
            StockBar.stock_id == stock_id,
            StockBar.timeframe == settings.ALPACA_TIMEFRAME,
            StockBar.provider == settings.ALPACA_PROVIDER,
            StockBar.feed == settings.ALPACA_FEED,
            StockBar.adjustment == settings.ALPACA_ADJUSTMENT,
        )
        .order_by(StockBar.timestamp.desc())
        .limit(1)
    )

    if latest_bar is None or latest_bar.close <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No usable historical price is available for this stock.",
        )

    return Decimal(str(latest_bar.close))


def get_estimated_buy_reservation(
    db: Session,
    stock_id,
    order_type: str,
    quantity: int,
    limit_price=None,
) -> Decimal:
    """
    Estimate the cash reservation for a buy order.

    Market orders:
        Latest close + 5% buffer.

    Limit orders:
        Limit price + trading fee.
    """

    if order_type == "limit":
        estimated_price = Decimal(str(limit_price))

        estimated_cost = (
            estimated_price
            * quantity
            * (Decimal("1") + TRADING_FEE_RATE)
        )

    else:
        latest_close = get_latest_close(
            db,
            stock_id,
        )

        estimated_cost = (
            latest_close
            * MARKET_ORDER_BUFFER
            * quantity
        )

    return estimated_cost


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

    Limit orders reserve their limit price plus fees.
    Market orders reserve the latest close plus a 5% buffer.
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

        if remaining_quantity <= 0:
            continue

        reserved_cash += get_estimated_buy_reservation(
            db=db,
            stock_id=order.stock_id,
            order_type=order.order_type,
            quantity=remaining_quantity,
            limit_price=order.limit_price,
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

    return sum(
        get_remaining_order_quantity(order)
        for order in pending_orders
    )


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

    try:
        # -------------------------------------------------
        # 1. Verify competition
        # -------------------------------------------------

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

        # -------------------------------------------------
        # 2. Verify agent
        # -------------------------------------------------

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

        # -------------------------------------------------
        # 3. Verify stock
        # -------------------------------------------------

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

        # -------------------------------------------------
        # 4. Lock portfolio
        # -------------------------------------------------

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

        # -------------------------------------------------
        # 5. Validate BUY order
        # -------------------------------------------------

        if order_data.side == "buy":

            new_order_estimate = get_estimated_buy_reservation(
                db=db,
                stock_id=stock.id,
                order_type=order_data.order_type,
                quantity=order_data.quantity,
                limit_price=order_data.limit_price,
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

        # -------------------------------------------------
        # 6. Validate SELL order
        # -------------------------------------------------

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

        # -------------------------------------------------
        # 7. Create pending order
        # -------------------------------------------------

        order = Order(
            portfolio_id=portfolio.id,
            stock_id=stock.id,
            side=order_data.side,
            order_type=order_data.order_type,
            quantity=order_data.quantity,
            limit_price=order_data.limit_price,
            status="pending",
        )

        db.add(order)
        db.flush()

        db.commit()
        db.refresh(order)

        return order

    except Exception:
        db.rollback()
        raise




def submit_order_batch(
    db: Session,
    competition_id,
    agent_id,
    orders,
) -> list[Order]:
    """
    Validate and submit multiple orders atomically.

    All orders are validated before any are created.
    If validation fails, the entire batch is rolled back.
    """

    try:
        # -------------------------------------------------
        # 1. Verify competition
        # -------------------------------------------------

                # -------------------------------------------------
        # 0. Reject duplicate stock symbols
        # -------------------------------------------------

        symbols = [
            order.stock_symbol
            for order in orders
        ]

        if len(symbols) != len(set(symbols)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A batch cannot contain multiple orders for the same stock.",
            )



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

        # -------------------------------------------------
        # 2. Verify agent
        # -------------------------------------------------

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

        # -------------------------------------------------
        # 3. Lock portfolio
        # -------------------------------------------------

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

        # -------------------------------------------------
        # 4. Resolve all stocks
        # -------------------------------------------------

        symbols = [
            order.stock_symbol
            for order in orders
        ]

        stocks = db.scalars(
            select(Stock).where(
                Stock.symbol.in_(symbols),
                Stock.is_active.is_(True),
                Stock.asset_type == "stock",
            )
        ).all()

        stocks_by_symbol = {
            stock.symbol: stock
            for stock in stocks
        }

        missing_symbols = [
            symbol
            for symbol in symbols
            if symbol not in stocks_by_symbol
        ]

        if missing_symbols:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "One or more stocks are unavailable.",
                    "symbols": missing_symbols,
                },
            )

        # -------------------------------------------------
        # 5. Calculate existing reserved cash
        # -------------------------------------------------

        reserved_cash = get_reserved_buying_power(
            db,
            portfolio.id,
        )

        available_cash = (
            Decimal(str(portfolio.cash_balance))
            - reserved_cash
        )

        proposed_buy_reservation = Decimal("0")

        # -------------------------------------------------
        # 6. Validate every proposed order
        # -------------------------------------------------

        for order_data in orders:

            stock = stocks_by_symbol[
                order_data.stock_symbol
            ]

            if order_data.side == "buy":

                proposed_buy_reservation += (
                    get_estimated_buy_reservation(
                        db=db,
                        stock_id=stock.id,
                        order_type=order_data.order_type,
                        quantity=order_data.quantity,
                        limit_price=order_data.limit_price,
                    )
                )

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
                        detail={
                            "message": "Insufficient shares for sell order.",
                            "symbol": order_data.stock_symbol,
                            "requested_quantity": order_data.quantity,
                            "owned_quantity": 0,
                        },
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
                            "symbol": order_data.stock_symbol,
                            "owned_quantity": position.quantity,
                            "reserved_quantity": reserved_quantity,
                            "available_quantity": available_quantity,
                            "requested_quantity": order_data.quantity,
                        },
                    )

        # -------------------------------------------------
        # 7. Validate cumulative BUY buying power
        # -------------------------------------------------

        if proposed_buy_reservation > available_cash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Insufficient available cash for the entire batch.",
                    "cash_balance": str(portfolio.cash_balance),
                    "reserved_cash": str(reserved_cash),
                    "available_cash": str(available_cash),
                    "proposed_buy_reservation": str(
                        proposed_buy_reservation
                    ),
                },
            )

        # -------------------------------------------------
        # 8. Create all orders
        # -------------------------------------------------

        created_orders = []

        for order_data in orders:

            stock = stocks_by_symbol[
                order_data.stock_symbol
            ]

            order = Order(
                portfolio_id=portfolio.id,
                stock_id=stock.id,
                side=order_data.side,
                order_type=order_data.order_type,
                quantity=order_data.quantity,
                limit_price=order_data.limit_price,
                status="pending",
            )

            db.add(order)
            created_orders.append(order)

        # One flush and one commit for the entire batch.
        db.flush()
        db.commit()

        for order in created_orders:
            db.refresh(order)

        return created_orders

    except Exception:
        db.rollback()
        raise

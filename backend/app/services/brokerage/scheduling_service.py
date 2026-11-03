
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, Competition, Order, Portfolio
from app.services.trading.calendar_service import get_next_market_open


def schedule_orders(
    db: Session,
    orders: list[Order],
    commit: bool = True,
) -> list[Order]:
    """
    Schedule only the supplied pending orders.

    Each order is assigned the next market open after
    its submission timestamp.

    This is intended for the autonomous trading coordinator,
    which must not accidentally reschedule unrelated orders.
    """

    if not orders:
        return []

    try:
        for order in orders:
            if order.status != "pending":
                raise ValueError(
                    f"Order {order.id} is not pending and "
                    "cannot be scheduled."
                )

            order.scheduled_execution_at = get_next_market_open(
                order.submitted_at
            )
            order.status = "queued"

        db.flush()

        if commit:
            db.commit()

            for order in orders:
                db.refresh(order)

        return orders

    except Exception:
        if commit:
            db.rollback()

        raise


def schedule_pending_orders(
    db: Session,
    competition_id: UUID,
) -> list[Order]:
    """
    Schedule all pending orders in an active competition.

    Each order is scheduled for the next market open after
    its submission timestamp.

    This function is retained for the existing API endpoint.
    """

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
            detail="Only active competitions can schedule orders.",
        )

    pending_orders = db.scalars(
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
            Order.status == "pending",
        )
        .order_by(Order.submitted_at.asc())
        .with_for_update()
    ).all()

    return schedule_orders(
        db=db,
        orders=pending_orders,
    )

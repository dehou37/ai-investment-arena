
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, Competition, Order, Portfolio
from app.services.trading.calendar_service import get_next_market_open


def schedule_pending_orders(
    db: Session,
    competition_id: UUID,
) -> list[Order]:
    """
    Schedule all pending orders in an active competition.

    Each order is scheduled for the next market open after
    its submission timestamp.
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

    if not pending_orders:
        return []

    try:
        for order in pending_orders:
            order.scheduled_execution_at = get_next_market_open(
                order.submitted_at
            )
            order.status = "queued"

        db.commit()

        for order in pending_orders:
            db.refresh(order)

        return pending_orders

    except Exception:
        db.rollback()
        raise

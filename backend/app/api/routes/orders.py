
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.order import OrderCreate, OrderResponse
from app.services.brokerage.order_service import submit_order
from app.services.brokerage.scheduling_service import (
    schedule_pending_orders,
)
from app.services.brokerage.execution_service import (
    execute_queued_orders,
)


router = APIRouter(
    prefix="/api/competitions",
    tags=["Brokerage"],
)

@router.post(
    "/{competition_id}/orders/execute",
    response_model=list[OrderResponse],
)
def execute_orders(
    competition_id: UUID,
    db: Session = Depends(get_db),
):
    return execute_queued_orders(db, competition_id)

@router.post(
    "/{competition_id}/agents/{agent_id}/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)

@router.post(
    "/{competition_id}/orders/schedule",
    response_model=list[OrderResponse],
)
def schedule_orders(
    competition_id: UUID,
    db: Session = Depends(get_db),
):
    return schedule_pending_orders(
        db=db,
        competition_id=competition_id,
    )

def create_order(
    competition_id: UUID,
    agent_id: UUID,
    order_data: OrderCreate,
    db: Session = Depends(get_db),


):
    return submit_order(
        db=db,
        competition_id=competition_id,
        agent_id=agent_id,
        order_data=order_data,
    )


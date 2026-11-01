from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.models.agent import Agent
from app.models.agent_daily_run import AgentDailyRun
from app.models.execution import Execution
from app.models.order import Order
from app.models.portfolio import Portfolio

from app.schemas.activity import (
    DailyRunActivityResponse,
    OrderActivityResponse,
    TradeActivityResponse,
)


router = APIRouter(
    prefix="/api/competitions",
    tags=["Agent Activity"],
)


def verify_agent(
    db: Session,
    competition_id: UUID,
    agent_id: UUID,
) -> None:
    agent = db.scalar(
        select(Agent.id).where(
            Agent.id == agent_id,
            Agent.competition_id == competition_id,
        )
    )

    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found in this competition.",
        )


@router.get(
    "/{competition_id}/agents/{agent_id}/activity/orders",
    response_model=list[OrderActivityResponse],
)
def get_agent_orders(
    competition_id: UUID,
    agent_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    verify_agent(db, competition_id, agent_id)

    orders = db.scalars(
        select(Order)
        .join(Portfolio, Order.portfolio_id == Portfolio.id)
        .join(Agent, Portfolio.agent_id == Agent.id)
        .where(
            Agent.id == agent_id,
            Agent.competition_id == competition_id,
        )
        .options(
            joinedload(Order.stock),
            selectinload(Order.executions),
        )
        .order_by(Order.submitted_at.desc())
        .limit(limit)
    ).all()

    return [
        {
            "id": order.id,
            "stock_symbol": order.stock.symbol,
            "side": order.side,
            "order_type": order.order_type,
            "quantity": order.quantity,
            "limit_price": order.limit_price,
            "status": order.status,
            "submitted_at": order.submitted_at,
            "scheduled_execution_at": order.scheduled_execution_at,
            "executions": order.executions,
        }
        for order in orders
    ]


@router.get(
    "/{competition_id}/agents/{agent_id}/activity/executions",
    response_model=list[TradeActivityResponse],
)
def get_agent_executions(
    competition_id: UUID,
    agent_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    verify_agent(db, competition_id, agent_id)

    executions = db.scalars(
        select(Execution)
        .join(Order, Execution.order_id == Order.id)
        .join(Portfolio, Order.portfolio_id == Portfolio.id)
        .join(Agent, Portfolio.agent_id == Agent.id)
        .where(
            Agent.id == agent_id,
            Agent.competition_id == competition_id,
        )
        .options(
            joinedload(Execution.order).joinedload(Order.stock),
        )
        .order_by(Execution.executed_at.desc())
        .limit(limit)
    ).all()

    return [
        {
            "id": execution.id,
            "stock_symbol": execution.order.stock.symbol,
            "side": execution.order.side,
            "quantity": execution.quantity,
            "execution_price": execution.execution_price,
            "fees": execution.fees,
            "slippage": execution.slippage,
            "executed_at": execution.executed_at,
        }
        for execution in executions
    ]


@router.get(
    "/{competition_id}/agents/{agent_id}/activity/daily-runs",
    response_model=list[DailyRunActivityResponse],
)
def get_agent_daily_runs(
    competition_id: UUID,
    agent_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    verify_agent(db, competition_id, agent_id)

    runs = db.scalars(
        select(AgentDailyRun)
        .where(
            AgentDailyRun.agent_id == agent_id,
            AgentDailyRun.competition_id == competition_id,
        )
        .order_by(
            AgentDailyRun.trading_date.desc(),
            AgentDailyRun.started_at.desc(),
        )
        .limit(limit)
    ).all()

    return runs
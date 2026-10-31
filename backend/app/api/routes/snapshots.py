from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.portfolio_snapshot import (
    AgentSnapshotHistoryResponse,
    SnapshotCreationResponse,
)
from app.services.brokerage.snapshot_service import (
    create_daily_snapshots,
    get_agent_snapshots,
)


router = APIRouter(
    prefix="/api/competitions",
    tags=["Portfolio Snapshots"],
)


# ---------------------------------------------------------
# POST /api/competitions/{competition_id}/snapshots
# Create daily snapshots for all agents
# ---------------------------------------------------------

@router.post(
    "/{competition_id}/snapshots",
    response_model=SnapshotCreationResponse,
)
def create_snapshots(
    competition_id: UUID,
    snapshot_date: date = Query(
        ...,
        description="Completed trading date in New York.",
    ),
    db: Session = Depends(get_db),
):
    return create_daily_snapshots(
        db=db,
        competition_id=competition_id,
        snapshot_date=snapshot_date,
    )


# ---------------------------------------------------------
# GET /api/competitions/{competition_id}/agents/{agent_id}/snapshots
# Retrieve an agent's historical portfolio snapshots
# ---------------------------------------------------------

@router.get(
    "/{competition_id}/agents/{agent_id}/snapshots",
    response_model=AgentSnapshotHistoryResponse,
)
def get_snapshots(
    competition_id: UUID,
    agent_id: UUID,
    db: Session = Depends(get_db),
):
    result = get_agent_snapshots(
        db=db,
        competition_id=competition_id,
        agent_id=agent_id,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Competition, agent or portfolio not found.",
        )

    return result
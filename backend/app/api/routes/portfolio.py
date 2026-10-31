from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.portfolio import (
    LeaderboardEntryResponse,
    PortfolioResponse,
)
from app.services.brokerage.portfolio_service import (
    get_agent_portfolio,
    get_competition_leaderboard,
)


router = APIRouter(
    prefix="/api/competitions",
    tags=["Portfolios"],
)


# ---------------------------------------------------------
# GET /api/competitions/{competition_id}/agents/{agent_id}/portfolio
# Get an individual agent's portfolio valuation
# ---------------------------------------------------------

@router.get(
    "/{competition_id}/agents/{agent_id}/portfolio",
    response_model=PortfolioResponse,
)
def get_portfolio(
    competition_id: UUID,
    agent_id: UUID,
    db: Session = Depends(get_db),
):
    result = get_agent_portfolio(
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


# ---------------------------------------------------------
# GET /api/competitions/{competition_id}/leaderboard
# Rank all agents by total return
# ---------------------------------------------------------

@router.get(
    "/{competition_id}/leaderboard",
    response_model=list[LeaderboardEntryResponse],
)
def get_leaderboard(
    competition_id: UUID,
    db: Session = Depends(get_db),
):
    result = get_competition_leaderboard(
        db=db,
        competition_id=competition_id,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Competition not found.",
        )

    return result
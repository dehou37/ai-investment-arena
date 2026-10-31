
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models import (
    Agent,
    Competition,
    Portfolio,
    Stock,
)
from app.schemas.competition import (
    CompetitionCreate,
    CompetitionResponse,
)


router = APIRouter(
    prefix="/api/competitions",
    tags=["Competitions"],
)


# ---------------------------------------------------------
# Default AI agents created for every new competition
# ---------------------------------------------------------

INITIAL_AGENTS = [
    {
        "name": "Warren",
        "strategy_type": "buy_and_hold",
        "description": (
            "A long-term investor focused on holding quality companies."
        ),
    },
    {
        "name": "Momentum",
        "strategy_type": "momentum",
        "description": (
            "Looks for stocks showing strong upward price momentum."
        ),
    },
    {
        "name": "Contrarian",
        "strategy_type": "mean_reversion",
        "description": (
            "Looks for stocks that may recover after significant price declines."
        ),
    },
    {
        "name": "Value Hunter",
        "strategy_type": "value",
        "description": (
            "Looks for companies trading at attractive valuations."
        ),
    },
    {
        "name": "Guardian",
        "strategy_type": "risk_managed",
        "description": (
            "Prioritizes risk management and capital preservation."
        ),
    },
]


# ---------------------------------------------------------
# Shared database query
# ---------------------------------------------------------

def get_competition_query():
    return (
        select(Competition)
        .options(
            selectinload(Competition.benchmark_stock),
            selectinload(Competition.agents).selectinload(
                Agent.portfolio
            ),
        )
    )


# ---------------------------------------------------------
# POST /api/competitions
# Create a competition with five agents and portfolios
# ---------------------------------------------------------

@router.post(
    "",
    response_model=CompetitionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_competition(
    competition_data: CompetitionCreate,
    db: Session = Depends(get_db),
):
    # Validate competition name.
    if not competition_data.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Competition name cannot be empty.",
        )

    # Validate competition duration.
    if competition_data.duration_days <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Competition duration must be greater than zero.",
        )

    # Validate starting capital.
    if competition_data.initial_cash <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Initial cash must be greater than zero.",
        )

    # Find the active SPY benchmark.
    benchmark = db.scalar(
        select(Stock).where(
            Stock.symbol == "SPY",
            Stock.asset_type == "etf",
            Stock.is_active.is_(True),
        )
    )

    if benchmark is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "SPY benchmark is missing or inactive. "
                "Please seed SPY first."
            ),
        )

    try:
        # Create competition.
        competition = Competition(
            name=competition_data.name.strip(),
            description=competition_data.description,
            status="pending",
            initial_cash=competition_data.initial_cash,
            duration_days=competition_data.duration_days,
            benchmark_stock_id=benchmark.id,
        )

        db.add(competition)
        db.flush()

        # Create agents and their virtual portfolios.
        for agent_data in INITIAL_AGENTS:
            agent = Agent(
                competition_id=competition.id,
                name=agent_data["name"],
                strategy_type=agent_data["strategy_type"],
                description=agent_data["description"],
                config={},
                status="active",
            )

            db.add(agent)
            db.flush()

            portfolio = Portfolio(
                agent_id=agent.id,
                cash_balance=competition_data.initial_cash,
            )

            db.add(portfolio)

        # Commit competition, agents and portfolios together.
        db.commit()

    except Exception:
        db.rollback()
        raise

    # Reload competition with related records.
    result = db.scalar(
        get_competition_query().where(
            Competition.id == competition.id
        )
    )

    return result


# ---------------------------------------------------------
# GET /api/competitions
# List all competitions
# ---------------------------------------------------------

@router.get(
    "",
    response_model=list[CompetitionResponse],
)
def list_competitions(
    db: Session = Depends(get_db),
):
    result = db.scalars(
        get_competition_query().order_by(
            Competition.created_at.desc()
        )
    ).all()

    return result


# ---------------------------------------------------------
# GET /api/competitions/{competition_id}
# Retrieve a specific competition
# ---------------------------------------------------------

@router.get(
    "/{competition_id}",
    response_model=CompetitionResponse,
)
def get_competition(
    competition_id: UUID,
    db: Session = Depends(get_db),
):
    competition = db.scalar(
        get_competition_query().where(
            Competition.id == competition_id
        )
    )

    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Competition not found.",
        )

    return competition


# ---------------------------------------------------------
# POST /api/competitions/{competition_id}/start
# Start a pending competition
# ---------------------------------------------------------

@router.post(
    "/{competition_id}/start",
    response_model=CompetitionResponse,
)
def start_competition(
    competition_id: UUID,
    db: Session = Depends(get_db),
):
    competition = db.scalar(
        get_competition_query().where(
            Competition.id == competition_id
        )
    )

    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Competition not found.",
        )

    if competition.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot start competition with status "
                f"'{competition.status}'. "
                "Only pending competitions can start."
            ),
        )

    competition.status = "active"
    competition.started_at = datetime.now(timezone.utc)

    db.commit()

    return db.scalar(
        get_competition_query().where(
            Competition.id == competition_id
        )
    )


# ---------------------------------------------------------
# POST /api/competitions/{competition_id}/complete
# Complete an active competition
# ---------------------------------------------------------

@router.post(
    "/{competition_id}/complete",
    response_model=CompetitionResponse,
)
def complete_competition(
    competition_id: UUID,
    db: Session = Depends(get_db),
):
    competition = db.scalar(
        get_competition_query().where(
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
            detail=(
                f"Cannot complete competition with status "
                f"'{competition.status}'. "
                "Only active competitions can complete."
            ),
        )

    competition.status = "completed"
    competition.completed_at = datetime.now(timezone.utc)

    db.commit()

    return db.scalar(
        get_competition_query().where(
            Competition.id == competition_id
        )
    )

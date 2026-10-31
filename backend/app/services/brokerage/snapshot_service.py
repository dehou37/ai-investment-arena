from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Agent,
    Competition,
    Portfolio,
    PortfolioSnapshot,
)
from app.services.brokerage.portfolio_service import (
    calculate_portfolio_valuation,
    get_raw_close_for_session,
)
from app.services.trading.calendar_service import (
    get_market_session_close,
)


NEW_YORK = ZoneInfo("America/New_York")


def create_daily_snapshots(
    db: Session,
    competition_id: UUID,
    snapshot_date: date,
):
    """
    Create one daily snapshot for each agent in a competition.

    Snapshots can only be recorded for the current New York
    trading date, after that session has closed.

    Existing snapshots are skipped to prevent duplicates.
    Incomplete valuations are skipped rather than recorded
    as valid performance results.
    """

    competition = db.scalar(
        select(Competition)
        .options(
            selectinload(Competition.agents)
            .selectinload(Agent.portfolio),
            selectinload(Competition.benchmark_stock),
        )
        .where(Competition.id == competition_id)
    )

    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Competition not found.",
        )

    if competition.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only active competitions can record snapshots.",
        )

    today_in_new_york = datetime.now(NEW_YORK).date()

    if snapshot_date != today_in_new_york:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Snapshots can only be created for the current "
                "New York trading date. Historical backfilling "
                "is not supported by this service."
            ),
        )

    session_close = get_market_session_close(snapshot_date)

    if session_close is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The requested date is not an NYSE trading session.",
        )

    now = datetime.now(timezone.utc)

    if now < session_close:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The trading session has not closed yet.",
        )

    benchmark_bar = get_raw_close_for_session(
        db,
        competition.benchmark_stock_id,
        session_date=snapshot_date,
    )

    if benchmark_bar is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "SPY daily bar is unavailable for the requested date. "
                "Import completed market data before recording snapshots."
            ),
        )

    benchmark_close = Decimal(str(benchmark_bar.close))

    created_count = 0
    skipped_existing = []
    skipped_incomplete = []

    try:
        for agent in competition.agents:
            if agent.portfolio is None:
                skipped_incomplete.append({
                    "agent_id": str(agent.id),
                    "agent_name": agent.name,
                    "reason": "Agent has no portfolio.",
                })
                continue

            existing_snapshot = db.scalar(
                select(PortfolioSnapshot.id).where(
                    PortfolioSnapshot.portfolio_id == agent.portfolio.id,
                    PortfolioSnapshot.snapshot_date == snapshot_date,
                )
            )

            if existing_snapshot is not None:
                skipped_existing.append(agent.name)
                continue

            valuation = calculate_portfolio_valuation(
                db=db,
                portfolio=agent.portfolio,
                initial_cash=competition.initial_cash,
                as_of_date=snapshot_date,
                exact_session_date=snapshot_date,
            )

            if not valuation["valuation_complete"]:
                skipped_incomplete.append({
                    "agent_id": str(agent.id),
                    "agent_name": agent.name,
                    "reason": "Portfolio valuation is incomplete.",
                    "missing_price_symbols": (
                        valuation["missing_price_symbols"]
                    ),
                    "inconsistent_positions": (
                        valuation["inconsistent_positions"]
                    ),
                })
                continue

            snapshot = PortfolioSnapshot(
                portfolio_id=agent.portfolio.id,
                snapshot_date=snapshot_date,
                cash_balance=valuation["cash_balance"],
                market_value=valuation["market_value"],
                portfolio_equity=valuation["portfolio_equity"],
                realised_pnl=valuation["realised_pnl"],
                unrealised_pnl=valuation["unrealised_pnl"],
                total_pnl=valuation["total_pnl"],
                total_return_pct=valuation["total_return_pct"],
                total_fees=valuation["total_fees"],
                total_slippage=valuation["total_slippage"],
                benchmark_close=benchmark_close,
                valuation_complete=True,
            )

            db.add(snapshot)
            created_count += 1

        db.commit()

    except Exception:
        db.rollback()
        raise

    return {
        "competition_id": competition.id,
        "snapshot_date": snapshot_date,
        "created_count": created_count,
        "skipped_existing": skipped_existing,
        "skipped_incomplete": skipped_incomplete,
        "benchmark_symbol": competition.benchmark_stock.symbol,
        "benchmark_close": benchmark_close,
    }


def get_agent_snapshots(
    db: Session,
    competition_id: UUID,
    agent_id: UUID,
):
    """
    Retrieve historical snapshots for one agent.
    """

    agent = db.scalar(
        select(Agent)
        .options(selectinload(Agent.portfolio))
        .where(
            Agent.id == agent_id,
            Agent.competition_id == competition_id,
        )
    )

    if agent is None or agent.portfolio is None:
        return None

    snapshots = db.scalars(
        select(PortfolioSnapshot)
        .where(
            PortfolioSnapshot.portfolio_id == agent.portfolio.id,
        )
        .order_by(PortfolioSnapshot.snapshot_date.asc())
    ).all()

    return {
        "competition_id": competition_id,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "strategy_type": agent.strategy_type,
        "snapshots": snapshots,
    }
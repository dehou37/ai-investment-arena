
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models import Agent, AgentDailyRun, Competition
from app.services.brokerage.scheduling_service import schedule_orders
from app.services.trading.calendar_service import get_market_session_close
from app.services.trading.decision_service import DecisionOrchestrator

class DailyTradingError(Exception):
    """Raised when a daily trading operation cannot be completed."""

class DailyTradingCoordinator:
    def __init__(
        self,
        decision_orchestrator: DecisionOrchestrator,
        session_factory: sessionmaker = SessionLocal,
    ):
        self.decision_orchestrator = decision_orchestrator
        self.session_factory = session_factory

    def run_competition_for_session(
        self,
        competition_id: UUID,
        trading_date: date,
        submit_orders: bool = True,
    ) -> dict[str, Any]:
        """
        Process every active agent for one completed NYSE session.

        submit_orders=True:
            Generate decisions, submit actionable orders, and schedule them.

        submit_orders=False:
            Generate and record decisions only. No orders are submitted.
            This is intended for historical sessions missed while the
            application or computer was offline.
        """

        session_close = get_market_session_close(trading_date)

        if session_close is None:
            raise DailyTradingError(
                f"{trading_date} is not an NYSE trading session."
            )

        if session_close.tzinfo is None:
            session_close = session_close.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) < session_close:
            raise DailyTradingError(
                f"The NYSE session for {trading_date} has not closed yet."
            )

        with self.session_factory() as db:
            competition = db.scalar(
                select(Competition).where(
                    Competition.id == competition_id
                )
            )

            if competition is None:
                raise DailyTradingError("Competition not found.")

            if competition.status != "active":
                raise DailyTradingError(
                    "Only active competitions can run daily trading."
                )

            agents = list(
                db.scalars(
                    select(Agent)
                    .where(
                        Agent.competition_id == competition_id,
                        Agent.status == "active",
                    )
                    .order_by(Agent.name)
                ).all()
            )

            agent_ids = [agent.id for agent in agents]

        results = []

        for agent_id in agent_ids:
            result = self._process_agent(
                competition_id=competition_id,
                agent_id=agent_id,
                trading_date=trading_date,
                submit_orders=submit_orders,
            )
            results.append(result)

        succeeded = sum(
            1 for result in results
            if result["status"] == "succeeded"
        )
        failed = sum(
            1 for result in results
            if result["status"] == "failed"
        )
        skipped = sum(
            1 for result in results
            if result["status"] == "skipped"
        )

        return {
            "competition_id": str(competition_id),
            "trading_date": trading_date.isoformat(),
            "submit_orders": submit_orders,
            "total_agents": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "results": results,
        }

    def _process_agent(
        self,
        competition_id: UUID,
        agent_id: UUID,
        trading_date: date,
        submit_orders: bool,
    ) -> dict[str, Any]:
        """
        Process one agent in its own database session.

        A unique AgentDailyRun record prevents the same agent from
        being processed twice for the same competition session.

        Existing running, succeeded, or failed records are not retried
        automatically.
        """

        with self.session_factory() as db:
            daily_run = AgentDailyRun(
                competition_id=competition_id,
                agent_id=agent_id,
                trading_date=trading_date,
                status="running",
                started_at=datetime.now(timezone.utc),
            )

            db.add(daily_run)

            try:
                db.commit()
                db.refresh(daily_run)

            except IntegrityError:
                db.rollback()

                existing_run = db.scalar(
                    select(AgentDailyRun).where(
                        AgentDailyRun.competition_id == competition_id,
                        AgentDailyRun.agent_id == agent_id,
                        AgentDailyRun.trading_date == trading_date,
                    )
                )

                return {
                    "agent_id": str(agent_id),
                    "trading_date": trading_date.isoformat(),
                    "status": "skipped",
                    "reason": (
                        "A daily run already exists for this agent "
                        "and trading session."
                    ),
                    "existing_status": (
                        existing_run.status
                        if existing_run is not None
                        else None
                    ),
                    "orders_created": (
                        existing_run.orders_created
                        if existing_run is not None
                        else 0
                    ),
                }

            try:
                if submit_orders:
                    decision, orders = (
                        self.decision_orchestrator
                        .generate_and_submit_agent_orders(
                            db=db,
                            competition_id=competition_id,
                            agent_id=agent_id,
                            as_of_date=trading_date,
                        )
                    )

                    # Only schedule orders created by this agent's
                    # current daily run.
                    schedule_orders(
                        db=db,
                        orders=orders,
                    )

                else:
                    # Historical recovery: generate and record the
                    # decision, but do not submit or schedule orders.
                    decision = (
                        self.decision_orchestrator
                        .generate_agent_decision(
                            db=db,
                            competition_id=competition_id,
                            agent_id=agent_id,
                            as_of_date=trading_date,
                        )
                    )

                    orders = []

                daily_run.decision = decision.model_dump(
                    mode="json"
                )
                daily_run.orders_created = len(orders)
                daily_run.status = "succeeded"
                daily_run.completed_at = datetime.now(timezone.utc)

                db.commit()

                return {
                    "agent_id": str(agent_id),
                    "trading_date": trading_date.isoformat(),
                    "status": "succeeded",
                    "orders_created": len(orders),
                    "decision_summary": decision.summary,
                    "submit_orders": submit_orders,
                }

            except Exception as exc:
                db.rollback()

                # Reload the run because the previous transaction
                # may have been rolled back.
                daily_run = db.scalar(
                    select(AgentDailyRun).where(
                        AgentDailyRun.competition_id == competition_id,
                        AgentDailyRun.agent_id == agent_id,
                        AgentDailyRun.trading_date == trading_date,
                    )
                )

                if daily_run is not None:
                    daily_run.status = "failed"
                    daily_run.error_message = str(exc)[:2000]
                    daily_run.completed_at = datetime.now(timezone.utc)

                    db.commit()

                return {
                    "agent_id": str(agent_id),
                    "trading_date": trading_date.isoformat(),
                    "status": "failed",
                    "error": str(exc),
                    "orders_created": 0,
                    "submit_orders": submit_orders,
                }

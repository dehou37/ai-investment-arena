
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models import Agent, AgentDailyRun, Competition
from app.services.brokerage.scheduling_service import schedule_orders
from app.services.trading.calendar_service import (
    get_market_session_close,
)
from app.services.trading.decision_service import (
    DecisionOrchestrator,
)


class DailyTradingError(Exception):
    """Raised when daily trading orchestration cannot proceed."""


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
    ) -> dict[str, Any]:
        """
        Process every active agent sequentially for one
        completed NYSE trading session.

        Each agent receives an independent database session.

        A unique AgentDailyRun record prevents the same agent
        from being processed twice for the same competition
        and trading date.
        """

        # -------------------------------------------------
        # 1. Validate the requested NYSE session
        # -------------------------------------------------

        session_close = get_market_session_close(trading_date)

        if session_close is None:
            raise DailyTradingError(
                f"{trading_date} is not an NYSE trading session."
            )

        now = datetime.now(timezone.utc)

        if now < session_close:
            raise DailyTradingError(
                f"The NYSE session for {trading_date} "
                "has not closed yet."
            )

        # -------------------------------------------------
        # 2. Validate competition and retrieve active agents
        # -------------------------------------------------

        with self.session_factory() as db:

            competition = db.scalar(
                select(Competition).where(
                    Competition.id == competition_id
                )
            )

            if competition is None:
                raise DailyTradingError(
                    "Competition not found."
                )

            if competition.status != "active":
                raise DailyTradingError(
                    "Only active competitions can run daily trading."
                )

            agents = db.scalars(
                select(Agent)
                .where(
                    Agent.competition_id == competition_id,
                    Agent.status == "active",
                )
                .order_by(Agent.name.asc())
            ).all()

            agent_details = [
                (agent.id, agent.name)
                for agent in agents
            ]

        # -------------------------------------------------
        # 3. Process agents sequentially
        # -------------------------------------------------

        results = []

        for agent_id, agent_name in agent_details:

            result = self._process_agent(
                competition_id=competition_id,
                agent_id=agent_id,
                agent_name=agent_name,
                trading_date=trading_date,
            )

            results.append(result)

        # -------------------------------------------------
        # 4. Build competition-level summary
        # -------------------------------------------------

        return {
            "competition_id": str(competition_id),
            "trading_date": trading_date.isoformat(),
            "total_agents": len(results),
            "succeeded": sum(
                result["status"] == "succeeded"
                for result in results
            ),
            "failed": sum(
                result["status"] == "failed"
                for result in results
            ),
            "skipped": sum(
                result["status"] == "skipped"
                for result in results
            ),
            "agents": results,
        }

    def _process_agent(
        self,
        competition_id: UUID,
        agent_id: UUID,
        agent_name: str,
        trading_date: date,
    ) -> dict[str, Any]:
        """
        Claim and process one agent's daily run.

        The claim is committed before decision generation.
        Existing run records are never processed again.
        """

        with self.session_factory() as db:

            # ---------------------------------------------
            # 1. Claim this agent's daily run
            # ---------------------------------------------

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

                if existing_run is None:
                    raise

                return {
                    "agent_id": str(agent_id),
                    "agent_name": agent_name,
                    "status": "skipped",
                    "existing_run_status": existing_run.status,
                    "orders_created": existing_run.orders_created,
                }

            run_id = daily_run.id

            # ---------------------------------------------
            # 2. Generate and submit approved decisions
            # ---------------------------------------------

            try:
                decision, orders = (
                    self.decision_orchestrator
                    .generate_and_submit_agent_orders(
                        db=db,
                        competition_id=competition_id,
                        agent_id=agent_id,
                        as_of_date=trading_date,
                    )
                )

                # -----------------------------------------
                # 3. Schedule only this agent's new orders
                # -----------------------------------------

                schedule_orders(
                    db=db,
                    orders=orders,
                )

                # -----------------------------------------
                # 4. Record successful outcome
                # -----------------------------------------

                daily_run = db.get(
                    AgentDailyRun,
                    run_id,
                )

                daily_run.decision = decision.model_dump(
                    mode="json"
                )

                daily_run.orders_created = len(orders)
                daily_run.status = "succeeded"
                daily_run.completed_at = datetime.now(
                    timezone.utc
                )

                db.commit()

                return {
                    "agent_id": str(agent_id),
                    "agent_name": agent_name,
                    "status": "succeeded",
                    "orders_created": len(orders),
                }

            except Exception as error:

                # -----------------------------------------
                # 5. Record failure without stopping others
                # -----------------------------------------

                db.rollback()

                daily_run = db.get(
                    AgentDailyRun,
                    run_id,
                )

                if daily_run is not None:

                    daily_run.status = "failed"

                    daily_run.error_message = (
                        f"{type(error).__name__}: {error}"
                    )[:2000]

                    daily_run.completed_at = datetime.now(
                        timezone.utc
                    )

                    db.commit()

                return {
                    "agent_id": str(agent_id),
                    "agent_name": agent_name,
                    "status": "failed",
                    "orders_created": 0,
                    "error_message": str(error)[:2000],
                }

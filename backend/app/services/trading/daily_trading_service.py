
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models import Agent, AgentDailyRun, Competition
from app.schemas.agent_decision import AgentDecision
from app.services.brokerage.scheduling_service import schedule_orders
from app.services.trading.calendar_service import get_market_session_close
from app.services.trading.decision_service import DecisionOrchestrator

MAX_DAILY_RUN_ATTEMPTS = 3
STALE_DAILY_RUN_TIMEOUT = timedelta(minutes=30)

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
        historical_replay: bool = False,
    ) -> dict[str, Any]:
        """
        Process every active agent for one completed NYSE session.

        submit_orders=True:
            Generate decisions, submit actionable orders, and schedule them.

        submit_orders=False:
            Generate and record decisions only. No orders are submitted.
            This is for analysis-only runs, not missed-session replay.

        historical_replay=True:
            Treat the decision as generated at the session close and
            schedule its orders for the next NYSE open.
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
                historical_replay=historical_replay,
                submitted_at=(session_close if historical_replay else None),
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
        historical_replay: bool = False,
        submitted_at: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Process one agent in its own database session.

        A unique AgentDailyRun record prevents the same agent from
        being processed twice for the same competition session.

        Running and succeeded records are never retried. Failed records
        are retried up to MAX_DAILY_RUN_ATTEMPTS total attempts.
        """

        replay_decision = None

        with self.session_factory() as db:
            daily_run = AgentDailyRun(
                competition_id=competition_id,
                agent_id=agent_id,
                trading_date=trading_date,
                status="running",
                attempt_count=1,
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
                    ).with_for_update()
                )

                is_stale_running = (
                    existing_run is not None
                    and existing_run.status == "running"
                    and self._is_stale_run(existing_run.started_at)
                )
                is_retryable = (
                    existing_run is not None
                    and (
                        existing_run.status == "failed"
                        or is_stale_running
                    )
                    and existing_run.attempt_count
                    < MAX_DAILY_RUN_ATTEMPTS
                )

                if is_retryable:
                    if (
                        historical_replay
                        and self._decision_has_actionable_trades(
                            existing_run.decision
                        )
                    ):
                        replay_decision = AgentDecision.model_validate(
                            existing_run.decision
                        )

                    existing_run.status = "running"
                    existing_run.attempt_count += 1
                    existing_run.started_at = datetime.now(timezone.utc)
                    existing_run.completed_at = None
                    existing_run.error_message = None
                    if replay_decision is None:
                        existing_run.decision = None
                        existing_run.orders_created = 0
                    db.commit()
                    daily_run = existing_run
                elif (
                    historical_replay
                    and existing_run is not None
                    and existing_run.status == "succeeded"
                    and existing_run.orders_created == 0
                    and self._decision_has_actionable_trades(
                        existing_run.decision
                    )
                ):
                    replay_decision = AgentDecision.model_validate(
                        existing_run.decision
                    )
                    existing_run.status = "running"
                    existing_run.started_at = datetime.now(timezone.utc)
                    existing_run.completed_at = None
                    existing_run.error_message = None
                    db.commit()
                    daily_run = existing_run
                else:
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
                        "attempt_count": (
                            existing_run.attempt_count
                            if existing_run is not None
                            else 0
                        ),
                        "orders_created": (
                            existing_run.orders_created
                            if existing_run is not None
                            else 0
                        ),
                    }

            try:
                if replay_decision is not None:
                    decision = replay_decision
                    orders = (
                        self.decision_orchestrator
                        .submit_decision_orders(
                            db=db,
                            competition_id=competition_id,
                            agent_id=agent_id,
                            decision=decision,
                            as_of_date=trading_date,
                            submitted_at=submitted_at,
                            commit=False,
                        )
                    )
                    schedule_orders(
                        db=db,
                        orders=orders,
                        commit=False,
                    )

                elif submit_orders:
                    order_submission_options = {
                        "db": db,
                        "competition_id": competition_id,
                        "agent_id": agent_id,
                        "as_of_date": trading_date,
                        "commit": False,
                    }
                    if submitted_at is not None:
                        order_submission_options["submitted_at"] = (
                            submitted_at
                        )

                    decision, orders = (
                        self.decision_orchestrator
                        .generate_and_submit_agent_orders(
                            **order_submission_options,
                        )
                    )

                    # Only schedule orders created by this agent's
                    # current daily run.
                    schedule_orders(
                        db=db,
                        orders=orders,
                        commit=False,
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
                    "attempt_count": daily_run.attempt_count,
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
                    "attempt_count": (
                        daily_run.attempt_count
                        if daily_run is not None
                        else 0
                    ),
                    "submit_orders": submit_orders,
                }

    @staticmethod
    def _decision_has_actionable_trades(
        decision: dict[str, Any] | None,
    ) -> bool:
        if not isinstance(decision, dict):
            return False

        trades = decision.get("decisions", [])
        return any(
            isinstance(trade, dict)
            and trade.get("action") in {"buy", "sell"}
            for trade in trades
        )

    @staticmethod
    def _is_stale_run(started_at: datetime) -> bool:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        return started_at <= (
            datetime.now(timezone.utc) - STALE_DAILY_RUN_TIMEOUT
        )

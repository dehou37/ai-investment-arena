from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models import Competition
from app.services.brokerage.execution_service import (
    execute_queued_orders,
)
from app.services.market_data.alpaca import (
    AlpacaMarketDataClient,
)
from app.services.market_data.competition_ingestion_service import (
    get_competition_session_data_status,
    ingest_competition_session,
)
from app.services.trading.calendar_service import (
    get_completed_market_sessions,
)
from app.services.trading.recovery_service import (
    DailyTradingRecoveryService,
)


class AutonomousTradingService:
    """
    Coordinates the autonomous daily trading workflow.

    Workflow:
    1. Find completed NYSE sessions.
    2. Ensure market data is complete for each session.
    3. Stop at the first incomplete session.
    4. Replay historical executions and decisions chronologically.
    5. Run monitored execution as a final current-session safeguard.

    Ingestion and execution use separate database sessions.
    """

    def __init__(
        self,
        client: AlpacaMarketDataClient,
        recovery_service: DailyTradingRecoveryService,
        session_factory: sessionmaker = SessionLocal,
        execute_orders_fn: Callable = execute_queued_orders,
    ):
        self.client = client
        self.recovery_service = recovery_service
        self.session_factory = session_factory
        self.execute_orders_fn = execute_orders_fn

    def run_competition(
        self,
        competition_id: UUID,
    ) -> dict[str, Any]:
        """
        Process all eligible sessions for one active competition.
        """

        with self.session_factory() as db:
            competition = db.scalar(
                select(Competition).where(
                    Competition.id == competition_id
                )
            )

            if competition is None:
                raise ValueError("Competition not found.")

            if competition.status != "active":
                raise ValueError(
                    "Only active competitions can be processed."
                )

            if competition.started_at is None:
                raise ValueError(
                    "Competition has no start timestamp."
                )

            started_at = competition.started_at

        completed_sessions = get_completed_market_sessions(
            started_at=started_at,
        )

        ready_sessions = set()
        ingestion_results = []
        blocked_session = None
        ingestion_error = None

        # Process sessions chronologically.
        for trading_date in completed_sessions:
            try:
                with self.session_factory() as db:
                    data_status = (
                        get_competition_session_data_status(
                            db=db,
                            competition_id=competition_id,
                            session_date=trading_date,
                        )
                    )

                    if data_status["status"] == "incomplete":
                        ingestion_result = (
                            ingest_competition_session(
                                db=db,
                                client=self.client,
                                competition_id=competition_id,
                                session_date=trading_date,
                            )
                        )

                        # Persist whatever valid bars were received.
                        db.commit()

                        # Verify persisted data after committing.
                        data_status = (
                            get_competition_session_data_status(
                                db=db,
                                competition_id=competition_id,
                                session_date=trading_date,
                            )
                        )

                        ingestion_results.append({
                            "session_date": trading_date.isoformat(),
                            "ingestion": ingestion_result,
                            "verified_status": data_status["status"],
                        })

                    else:
                        ingestion_results.append({
                            "session_date": trading_date.isoformat(),
                            "ingestion": None,
                            "verified_status": "complete",
                        })

                if data_status["status"] != "complete":
                    blocked_session = trading_date.isoformat()
                    break

                ready_sessions.add(trading_date)

            except Exception as exc:
                ingestion_error = {
                    "session_date": trading_date.isoformat(),
                    "error": str(exc),
                }

                blocked_session = trading_date.isoformat()
                break

        # Replay ready sessions first. The recovery service fills due
        # orders from the exact historical session before generating
        # decisions for that session.
        recovery_result = self.recovery_service.recover_competition(
            competition_id=competition_id,
            ready_sessions=ready_sessions,
        )

        # Keep the normal monitored path as a safeguard, but only run it
        # after historical replay and only with complete latest-session data.
        execution_result = None
        execution_error = None

        if completed_sessions and completed_sessions[-1] in ready_sessions:
            try:
                with self.session_factory() as db:
                    executed_orders = self.execute_orders_fn(
                        db,
                        competition_id,
                    )

                    execution_result = {
                        "orders_returned": len(executed_orders),
                    }

            except Exception as exc:
                execution_error = str(exc)

        return {
            "competition_id": str(competition_id),
            "sessions_found": len(completed_sessions),
            "sessions_ready": len(ready_sessions),
            "blocked_session": blocked_session,
            "ingestion_error": ingestion_error,
            "ingestion_results": ingestion_results,
            "execution": execution_result,
            "execution_error": execution_error,
            "recovery": recovery_result,
        }

    def run_all_active_competitions(
        self,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Complete expired competitions, then process remaining active ones.
        """

        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        else:
            current_time = current_time.astimezone(timezone.utc)

        with self.session_factory() as db:
            active_competitions = db.scalars(
                select(Competition).where(
                    Competition.status == "active",
                    Competition.started_at.is_not(None),
                )
            ).all()

            completed_count = 0
            for competition in active_competitions:
                started_at = competition.started_at
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                else:
                    started_at = started_at.astimezone(timezone.utc)

                end_at = started_at + timedelta(
                    days=competition.duration_days
                )
                if current_time >= end_at:
                    competition.status = "completed"
                    competition.completed_at = current_time
                    completed_count += 1

            if completed_count:
                db.commit()

            competition_ids = list(
                db.scalars(
                    select(Competition.id).where(
                        Competition.status == "active"
                    )
                ).all()
            )

        results = []

        for competition_id in competition_ids:
            try:
                result = self.run_competition(
                    competition_id=competition_id,
                )

                results.append({
                    "competition_id": str(competition_id),
                    "status": "succeeded",
                    "result": result,
                })

            except Exception as exc:
                results.append({
                    "competition_id": str(competition_id),
                    "status": "failed",
                    "error": str(exc),
                })

        return {
            "total_competitions": len(competition_ids),
            "completed_competitions": completed_count,
            "succeeded": sum(
                1 for result in results
                if result["status"] == "succeeded"
            ),
            "failed": sum(
                1 for result in results
                if result["status"] == "failed"
            ),
            "results": results,
        }
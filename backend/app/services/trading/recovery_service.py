from datetime import date
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.database import SessionLocal
from app.models import Competition, MarketSessionMonitor
from app.services.brokerage.execution_service import (
    execute_queued_orders,
)
from app.services.trading.calendar_service import (
    get_completed_market_sessions,
)
from app.services.trading.daily_trading_service import (
    DailyTradingCoordinator,
)



class DailyTradingRecoveryService:
    """
    Recovers completed daily trading sessions for active competitions.

    Ready sessions are replayed chronologically. Orders due on a session
    are filled from that session's historical bar before decisions are
    generated at its close and scheduled for the next market open.

    If monitoring is still active:
        Defer the latest session until monitoring completes.

    Existing daily runs are handled by DailyTradingCoordinator.
    """

    def __init__(
        self,
        coordinator: DailyTradingCoordinator,
        session_factory: sessionmaker = SessionLocal,
        execute_historical_orders_fn: Callable = execute_queued_orders,
    ):
        self.coordinator = coordinator
        self.session_factory = session_factory
        self.execute_historical_orders_fn = execute_historical_orders_fn

    def recover_competition(
        self,
        competition_id: UUID,
        ready_sessions: set[date] | None = None,
    ) -> dict[str, Any]:
        """
        Recover completed sessions for one active competition.
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
                    "Only active competitions can be recovered."
                )

            if competition.started_at is None:
                raise ValueError(
                    "Competition has no start timestamp."
                )

            started_at = competition.started_at

        completed_sessions = get_completed_market_sessions(
            started_at=started_at,
        )

        if not completed_sessions:
            return {
                "competition_id": str(competition_id),
                "sessions_found": 0,
                "sessions_processed": 0,
                "sessions_deferred": 0,
                "results": [],
            }

        latest_session = completed_sessions[-1]
        # When supplied, only sessions with complete market data
        # may be recovered.

        if ready_sessions is None:
            ready_session_dates = set(completed_sessions)
        else:
            ready_session_dates = ready_sessions

        sessions_to_process = [
            trading_date
            for trading_date in completed_sessions
            if trading_date in ready_session_dates
        ]
        # The latest session may still be in the live monitoring grace
        # period. Older sessions are replayed regardless of monitor state.
        with self.session_factory() as db:
            latest_monitor = db.scalar(
                select(MarketSessionMonitor).where(
                    MarketSessionMonitor.session_date == latest_session
                )
            )

            monitor_status = (
                latest_monitor.status
                if latest_monitor is not None
                else None
            )

        # If monitoring is still active, wait until the execution
        # grace period has ended and the monitor marks it completed.
        defer_latest_session = monitor_status == "monitoring"

        session_results = []
        replay_execution_results = []

        for trading_date in sessions_to_process:

            if (
                trading_date == latest_session
                and defer_latest_session
            ):
                continue

            with self.session_factory() as db:
                executed_orders = self.execute_historical_orders_fn(
                    db,
                    competition_id,
                    historical_session_date=trading_date,
                )
                replay_execution_results.append({
                    "session_date": trading_date.isoformat(),
                    "orders_processed": len(executed_orders),
                })

            result = self.coordinator.run_competition_for_session(
                competition_id=competition_id,
                trading_date=trading_date,
                submit_orders=True,
                historical_replay=True,
            )

            session_results.append(result)

        return {
            "competition_id": str(competition_id),
            "sessions_found": len(completed_sessions),
            "sessions_processed": len(session_results),
            "sessions_deferred": (
                1 if defer_latest_session else 0
            ),
            "sessions_skipped_data": (
                len(completed_sessions) - len(sessions_to_process)
            ),
            "latest_completed_session": latest_session.isoformat(),
            "latest_session_monitor_status": monitor_status,
            "historical_execution_results": replay_execution_results,
            "results": session_results,
        }

    def recover_all_active_competitions(self) -> dict[str, Any]:
        """
        Recover all currently active competitions.
        """

        with self.session_factory() as db:
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
                result = self.recover_competition(
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
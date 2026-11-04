
import asyncio
import logging
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text

from app.core.database import engine
from app.services.trading.autonomous_trading_service import (
    AutonomousTradingService,
)


logger = logging.getLogger("uvicorn.error")
SCHEDULER_ADVISORY_LOCK_ID = 68449291989201


@contextmanager
def acquire_scheduler_lock():
    """Hold one PostgreSQL advisory lock while autonomous work runs."""

    if engine.dialect.name != "postgresql":
        logger.warning(
            "PostgreSQL advisory locks are unavailable; "
            "scheduler coordination is process-local only."
        )
        yield True
        return

    with engine.connect() as connection:
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": SCHEDULER_ADVISORY_LOCK_ID},
            ).scalar()
        )
        connection.commit()

        try:
            yield acquired
        finally:
            if acquired:
                try:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": SCHEDULER_ADVISORY_LOCK_ID},
                    )
                    connection.commit()
                except Exception:
                    # Do not return a possibly locked connection to the pool.
                    connection.invalidate()
                    raise


class DailyTradingSchedulerService:
    """
    Periodically runs the complete autonomous trading workflow.

    The autonomous service handles:
    - Market-data readiness checks and ingestion.
    - Execution of eligible queued orders.
    - Historical decision recovery.
    - Latest-session decision generation.
    - Competition-level failure isolation.
    """

    def __init__(
        self,
        autonomous_service: AutonomousTradingService,
        interval_seconds: int = 60,
        lock_acquirer=None,
    ):
        if interval_seconds <= 0:
            raise ValueError(
                "Scheduler interval must be greater than zero."
            )

        self.autonomous_service = autonomous_service
        self.interval_seconds = interval_seconds
        self.lock_acquirer = lock_acquirer or acquire_scheduler_lock

    def run_once(self) -> dict[str, Any]:
        """
        Perform one complete autonomous trading check.
        """

        with self.lock_acquirer() as acquired:
            if not acquired:
                return {
                    "skipped": True,
                    "reason": "Another process holds the scheduler lock.",
                }

            return (
                self.autonomous_service
                .run_all_active_competitions()
            )

    async def run_forever(self) -> None:
        """
        Run autonomous trading checks continuously.

        Database and trading operations run in a worker thread
        so they do not block FastAPI's event loop.

        Checks are sequential, so a slow run cannot overlap
        with another scheduler run.
        """

        logger.info(
            "Daily trading scheduler started. "
            "Check interval: %s seconds.",
            self.interval_seconds,
        )

        while True:
            await asyncio.sleep(self.interval_seconds)

            try:
                result = await asyncio.to_thread(
                    self.run_once
                )

                logger.info(
                    "Daily trading scheduler check completed: %s",
                    result,
                )

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "Daily trading scheduler encountered an error."
                )

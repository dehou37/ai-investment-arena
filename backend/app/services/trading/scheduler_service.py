
import asyncio
import logging
from typing import Any

from app.services.trading.autonomous_trading_service import (
    AutonomousTradingService,
)


logger = logging.getLogger("uvicorn.error")


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
    ):
        if interval_seconds <= 0:
            raise ValueError(
                "Scheduler interval must be greater than zero."
            )

        self.autonomous_service = autonomous_service
        self.interval_seconds = interval_seconds

    def run_once(self) -> dict[str, Any]:
        """
        Perform one complete autonomous trading check.
        """

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

import asyncio
import logging
from typing import Any

from app.services.trading.recovery_service import (
    DailyTradingRecoveryService,
)


logger = logging.getLogger("uvicorn.error")


class DailyTradingSchedulerService:
    """
    Periodically checks for completed NYSE sessions and processes
    active competitions through the recovery service.

    The recovery service handles:
    - Historical decision-only recovery.
    - Deferring sessions that are still being monitored.
    - Submitting orders after a healthy session is completed.
    - Preventing duplicate daily agent runs.
    """

    def __init__(
        self,
        recovery_service: DailyTradingRecoveryService,
        interval_seconds: int = 60,
    ):
        if interval_seconds <= 0:
            raise ValueError(
                "Scheduler interval must be greater than zero."
            )

        self.recovery_service = recovery_service
        self.interval_seconds = interval_seconds

    def run_once(self) -> dict[str, Any]:
        """
        Perform one scheduled recovery/trading check.
        """

        return (
            self.recovery_service
            .recover_all_active_competitions()
        )

    async def run_forever(self) -> None:
        """
        Run scheduled checks continuously.

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
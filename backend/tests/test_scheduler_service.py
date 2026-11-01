import asyncio
from unittest.mock import Mock

import pytest

from app.services.trading.scheduler_service import (
    DailyTradingSchedulerService,
)


def test_run_once_calls_recovery_service():
    recovery_service = Mock()

    expected_result = {
        "total_competitions": 1,
        "succeeded": 1,
        "failed": 0,
        "results": [],
    }

    recovery_service.recover_all_active_competitions.return_value = (
        expected_result
    )

    scheduler = DailyTradingSchedulerService(
        recovery_service=recovery_service,
    )

    result = scheduler.run_once()

    assert result == expected_result
    recovery_service.recover_all_active_competitions.assert_called_once()


def test_scheduler_rejects_non_positive_interval():
    recovery_service = Mock()

    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        DailyTradingSchedulerService(
            recovery_service=recovery_service,
            interval_seconds=0,
        )

    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        DailyTradingSchedulerService(
            recovery_service=recovery_service,
            interval_seconds=-1,
        )


def test_background_scheduler_runs_and_cancels_cleanly():
    recovery_service = Mock()

    recovery_service.recover_all_active_competitions.return_value = {
        "total_competitions": 0,
        "succeeded": 0,
        "failed": 0,
        "results": [],
    }

    scheduler = DailyTradingSchedulerService(
        recovery_service=recovery_service,
        interval_seconds=0.01,
    )

    async def run_test():
        task = asyncio.create_task(
            scheduler.run_forever()
        )

        try:
            # Allow several scheduler intervals to pass.
            for _ in range(100):
                if recovery_service.recover_all_active_competitions.called:
                    break

                await asyncio.sleep(0.01)

            assert (
                recovery_service.recover_all_active_competitions.called
            )

        finally:
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run_test())
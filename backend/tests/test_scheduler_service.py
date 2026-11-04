
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.trading.scheduler_service import (
    DailyTradingSchedulerService,
)
from app.services.trading import scheduler_service


@contextmanager
def lock_acquired():
    yield True


@contextmanager
def lock_busy():
    yield False


def test_run_once_calls_autonomous_service():
    autonomous_service = Mock()

    expected_result = {
        "total_competitions": 1,
        "succeeded": 1,
        "failed": 0,
        "results": [],
    }

    autonomous_service.run_all_active_competitions.return_value = (
        expected_result
    )

    scheduler = DailyTradingSchedulerService(
        autonomous_service=autonomous_service,
        lock_acquirer=lock_acquired,
    )

    result = scheduler.run_once()

    assert result == expected_result

    autonomous_service.run_all_active_competitions.assert_called_once()


def test_run_once_skips_when_another_process_holds_lock():
    autonomous_service = Mock()
    scheduler = DailyTradingSchedulerService(
        autonomous_service=autonomous_service,
        lock_acquirer=lock_busy,
    )

    result = scheduler.run_once()

    assert result["skipped"] is True
    autonomous_service.run_all_active_competitions.assert_not_called()


def test_postgres_advisory_lock_is_released(monkeypatch):
    connection = Mock()
    connection.execute.side_effect = [
        Mock(scalar=Mock(return_value=True)),
        Mock(scalar=Mock(return_value=True)),
    ]
    connection_context = Mock()
    connection_context.__enter__ = Mock(return_value=connection)
    connection_context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(
        scheduler_service,
        "engine",
        SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"),
            connect=Mock(return_value=connection_context),
        ),
    )

    with scheduler_service.acquire_scheduler_lock() as acquired:
        assert acquired is True

    assert connection.execute.call_count == 2
    assert connection.commit.call_count == 2
    assert connection.invalidate.call_count == 0


def test_scheduler_rejects_non_positive_interval():
    autonomous_service = Mock()

    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        DailyTradingSchedulerService(
            autonomous_service=autonomous_service,
            interval_seconds=0,
        )

    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        DailyTradingSchedulerService(
            autonomous_service=autonomous_service,
            interval_seconds=-1,
        )


def test_background_scheduler_runs_and_cancels_cleanly():
    autonomous_service = Mock()

    autonomous_service.run_all_active_competitions.return_value = {
        "total_competitions": 0,
        "succeeded": 0,
        "failed": 0,
        "results": [],
    }

    scheduler = DailyTradingSchedulerService(
        autonomous_service=autonomous_service,
        interval_seconds=0.01,
        lock_acquirer=lock_acquired,
    )

    async def run_test():
        task = asyncio.create_task(
            scheduler.run_forever()
        )

        try:
            for _ in range(100):
                if autonomous_service.run_all_active_competitions.called:
                    break

                await asyncio.sleep(0.01)

            assert autonomous_service.run_all_active_competitions.called

        finally:
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run_test())

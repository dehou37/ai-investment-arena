
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models import MarketSessionMonitor
from app.services.trading.calendar_service import (
    get_market_session_close,
    get_market_session_open,
)
from zoneinfo import ZoneInfo

logger = logging.getLogger("uvicorn.error")

HEARTBEAT_INTERVAL_SECONDS = 60
MAX_HEARTBEAT_GAP = timedelta(seconds=180)
EXECUTION_GRACE_PERIOD = timedelta(minutes=15)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


class MarketSessionMonitorService:
    def __init__(
        self,
        session_factory: sessionmaker = SessionLocal,
        heartbeat_interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS,
        max_heartbeat_gap: timedelta = MAX_HEARTBEAT_GAP,
        execution_grace_period: timedelta = EXECUTION_GRACE_PERIOD,
    ):
        self.session_factory = session_factory
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.max_heartbeat_gap = max_heartbeat_gap
        self.execution_grace_period = execution_grace_period

    def _mark_previous_sessions_missed(
        self,
        db: Session,
        current_session_date,
    ) -> int:
        """
        Mark older monitoring sessions as missed.

        This handles sessions left unfinished when the backend
        was offline and restarted on a later trading date.
        """

        stale_monitors = db.scalars(
            select(MarketSessionMonitor)
            .where(
                MarketSessionMonitor.status == "monitoring",
                MarketSessionMonitor.session_date < current_session_date,
            )
            .with_for_update()
        ).all()

        for monitor in stale_monitors:
            monitor.status = "missed"
            monitor.missed_reason = (
                "Backend restarted or resumed on a later trading date "
                "before this session was completed."
            )

        return len(stale_monitors)



    def run_once(
        self,
        now: datetime | None = None,
    ) -> dict:
        """
        Record one heartbeat for the current New York calendar date.

        A session is eligible only if monitoring began before
        its market open and heartbeat continuity is maintained.

        Sessions first observed after market open are marked missed.
        """

        current_time = _as_utc(
            now or datetime.now(timezone.utc)
        )

        session_date = current_time.astimezone(
            ZoneInfo("America/New_York")
        ).date()

        session_open = get_market_session_open(session_date)
        session_close = get_market_session_close(session_date)

        # Holidays and weekends have no NYSE session to monitor.
        if session_open is None or session_close is None:
            return {
                "session_date": session_date.isoformat(),
                "status": "not_a_trading_session",
            }

        session_open = _as_utc(session_open)
        session_close = _as_utc(session_close)

        db: Session = self.session_factory()

        try:

            stale_count = self._mark_previous_sessions_missed(
                db=db,
                current_session_date=session_date,
            )

            if stale_count:
                db.commit()
                logger.warning(
                    "Marked %s previous market session(s) as missed.",
                    stale_count,
                )


            monitor = db.scalar(
                select(MarketSessionMonitor)
                .where(
                    MarketSessionMonitor.session_date == session_date
                )
                .with_for_update()
            )

            # No record exists. Register only if the backend is
            # running before the NYSE market opens.
            if monitor is None:

                if current_time < session_open:

                    monitor = MarketSessionMonitor(
                        session_date=session_date,
                        status="monitoring",
                        observed_at=current_time,
                        last_heartbeat_at=current_time,
                    )

                    db.add(monitor)
                    db.commit()

                    return {
                        "session_date": session_date.isoformat(),
                        "status": "monitoring",
                        "action": "session_registered",
                    }

                # The backend started too late. Do not allow a
                # later restart to register this session retroactively.
                monitor = MarketSessionMonitor(
                    session_date=session_date,
                    status="missed",
                    observed_at=current_time,
                    last_heartbeat_at=current_time,
                    completed_at=current_time,
                    missed_reason=(
                        "Backend first observed the session "
                        "after market open."
                    ),
                )

                db.add(monitor)
                db.commit()

                return {
                    "session_date": session_date.isoformat(),
                    "status": "missed",
                    "action": "late_start",
                }

            # Terminal states must never be reopened.
            if monitor.status in ("completed", "missed"):
                return {
                    "session_date": session_date.isoformat(),
                    "status": monitor.status,
                    "action": "no_change",
                }

            last_heartbeat = _as_utc(
                monitor.last_heartbeat_at
            )

            heartbeat_gap = current_time - last_heartbeat

            # A negative gap indicates a clock inconsistency.
            if heartbeat_gap < timedelta(0):
                monitor.status = "missed"
                monitor.completed_at = current_time
                monitor.missed_reason = (
                    "System clock moved backwards."
                )

            elif heartbeat_gap > self.max_heartbeat_gap:
                monitor.status = "missed"
                monitor.completed_at = current_time
                monitor.missed_reason = (
                    "Heartbeat interruption exceeded "
                    f"{self.max_heartbeat_gap.total_seconds()} seconds."
                )

            elif current_time > (
                session_close + self.execution_grace_period
            ):
                monitor.status = "completed"
                monitor.completed_at = current_time
                monitor.missed_reason = None

            else:
                monitor.last_heartbeat_at = current_time

            db.commit()

            return {
                "session_date": session_date.isoformat(),
                "status": monitor.status,
                "action": (
                    "heartbeat_updated"
                    if monitor.status == "monitoring"
                    else (
                        "session_completed"
                        if monitor.status == "completed"
                        else "session_marked_missed"
                    )
                ),
            }

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    async def run_forever(self) -> None:
        """
        Run the heartbeat monitor continuously.

        Individual database errors are logged. The monitor
        continues trying on the next heartbeat interval.
        """

        logger.info("Market session monitor started.")

        while True:
            try:
                result = self.run_once()

                logger.debug(
                    "Market session monitor: %s",
                    result,
                )

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "Market session heartbeat failed."
                )

            await asyncio.sleep(
                self.heartbeat_interval_seconds
            )

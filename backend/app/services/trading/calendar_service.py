
from datetime import datetime, timedelta, timezone

import pandas as pd
import pandas_market_calendars as mcal


def get_next_market_open(
    submitted_at: datetime,
) -> datetime:
    """
    Return the next NYSE session opening time after an order
    was submitted.

    The returned datetime is timezone-aware UTC.

    If an order is submitted before today's market open,
    it can be scheduled for today's open.

    If it is submitted after today's market open,
    it is scheduled for the next trading session.
    """

    # Database timestamps may be naive depending on the
    # SQLAlchemy column configuration. Treat naive timestamps
    # as UTC.
    submitted_timestamp = pd.Timestamp(submitted_at)

    if submitted_timestamp.tzinfo is None:
        submitted_timestamp = submitted_timestamp.tz_localize("UTC")
    else:
        submitted_timestamp = submitted_timestamp.tz_convert("UTC")

    # Convert to New York time to determine the relevant
    # trading calendar dates.
    new_york_timestamp = submitted_timestamp.tz_convert(
        "America/New_York"
    )

    start_date = new_york_timestamp.date()
    end_date = start_date + timedelta(days=14)

    calendar = mcal.get_calendar("NYSE")

    schedule = calendar.schedule(
        start_date=start_date,
        end_date=end_date,
    )

    if schedule.empty:
        raise ValueError(
            "Unable to find an upcoming NYSE trading session."
        )

    for _, session in schedule.iterrows():
        market_open = pd.Timestamp(session["market_open"])

        if market_open > submitted_timestamp:
            return market_open.to_pydatetime()

    raise ValueError(
        "No upcoming NYSE market open found within 14 days."
    )



def get_market_session_open(session_date):
    """
    Return the NYSE market open for a given trading date,
    in timezone-aware UTC.

    Returns None if the date is not an NYSE trading session.
    """

    calendar = mcal.get_calendar("NYSE")

    schedule = calendar.schedule(
        start_date=session_date,
        end_date=session_date,
    )

    if schedule.empty:
        return None

    return schedule.iloc[0]["market_open"].to_pydatetime()



def get_market_session_close(session_date):
    """
    Return the NYSE market close for a given trading date,
    in timezone-aware UTC.
    """

    calendar = mcal.get_calendar("NYSE")

    schedule = calendar.schedule(
        start_date=session_date,
        end_date=session_date,
    )

    if schedule.empty:
        return None

    return schedule.iloc[0]["market_close"].to_pydatetime()

    
def get_completed_market_sessions(
    started_at: datetime,
    now: datetime | None = None,
) -> list:
    """
    Return completed NYSE sessions since the competition started.

    Only include sessions whose market open occurred at or after
    the competition start time. This avoids including a partial
    trading session when a competition starts during market hours.

    Naive timestamps are treated as UTC.
    """

    if started_at.tzinfo is None:
        started_timestamp = pd.Timestamp(started_at).tz_localize("UTC")
    else:
        started_timestamp = pd.Timestamp(started_at).tz_convert("UTC")

    if now is None:
        now_timestamp = pd.Timestamp.now(tz="UTC")
    elif now.tzinfo is None:
        now_timestamp = pd.Timestamp(now).tz_localize("UTC")
    else:
        now_timestamp = pd.Timestamp(now).tz_convert("UTC")

    if started_timestamp >= now_timestamp:
        return []

    new_york_start = started_timestamp.tz_convert("America/New_York")
    new_york_now = now_timestamp.tz_convert("America/New_York")

    calendar = mcal.get_calendar("NYSE")

    schedule = calendar.schedule(
        start_date=new_york_start.date(),
        end_date=new_york_now.date(),
    )

    completed_sessions = []

    for session_date, session in schedule.iterrows():
        market_open = pd.Timestamp(session["market_open"])
        market_close = pd.Timestamp(session["market_close"])

        if (
            market_open >= started_timestamp
            and market_close <= now_timestamp
        ):
            completed_sessions.append(
                pd.Timestamp(session_date).date()
            )

    return completed_sessions

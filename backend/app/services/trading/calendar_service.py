
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
# File purpose: Finds trading sessions and candle boundaries, including holidays and early closes.
"""NYSE regular sessions, including holidays, early closes, and DST."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas_market_calendars as mcal

from config import NY_TIMEZONE
from timeframes import TIMEFRAMES


@dataclass(frozen=True)
class MarketSession:
    open: datetime
    close: datetime


# Require a timezone-aware datetime and convert it to America/New_York.
def aware_et(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must be timezone-aware")
    return value.astimezone(NY_TIMEZONE)


# Translate a configured timeframe, such as 33m or 4h, into a duration.
def timeframe_duration(timeframe: str) -> timedelta:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    spec = TIMEFRAMES[timeframe]
    minutes = spec["multiplier"] * (60 if spec["timespan"] == "hour" else 1)
    return timedelta(minutes=minutes)


# Create and reuse the NYSE calendar used to determine valid trading sessions.
@lru_cache(maxsize=1)
def _calendar():
    return mcal.get_calendar("NYSE")


# Return session opens and closes for the dates, excluding exchange holidays and weekends.
@lru_cache(maxsize=128)
def sessions(start: date, end: date) -> tuple[MarketSession, ...]:
    """Inclusive date range; no sessions on exchange holidays/weekends."""
    if start > end:
        return ()
    schedule = _calendar().schedule(start_date=start, end_date=end)
    return tuple(
        MarketSession(
            row.market_open.to_pydatetime().astimezone(NY_TIMEZONE),
            row.market_close.to_pydatetime().astimezone(NY_TIMEZONE),
        )
        for row in schedule.itertuples()
    )


# Split a session into candle intervals and keep a shortened final interval at the session close.
def intervals(session: MarketSession, timeframe: str):
    duration = timeframe_duration(timeframe)
    start = session.open
    while start < session.close:
        end = min(start + duration, session.close)
        yield start, end
        start = end

# File purpose: Downloads Massive minute OHLC data and builds completed, session-aligned candles.
"""Massive OHLC fetching; build session-anchored candles from minute aggregates.

All public ranges contain whole intervals: candle.start_time >= start and
candle.timestamp <= end. Returned candles are completed by the configured
availability cutoff. Empty success is distinct from FetchError.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, time as day_time, timedelta, timezone
from email.utils import parsedate_to_datetime
from math import isfinite
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from candle import Candle
from config import (
    DATA_DELAY_SECONDS, HISTORY_MAX_LOOKBACK_DAYS, MASSIVE_BASE_URL,
    MAX_CANDLES, NY_TIMEZONE, REQUEST_MAX_ATTEMPTS, REQUEST_TIMEOUT_SECONDS,
    load_environment, require_environment,
)
from market_calendar import aware_et, intervals, sessions, timeframe_duration

LOG = logging.getLogger(__name__)
MINUTE = timedelta(minutes=1)


class FetchError(RuntimeError):
    """Controlled retrieval failure; callers must not treat this as empty data."""


class AuthenticationError(FetchError):
    """Invalid key or data entitlement; retries will not fix this."""


class DataError(FetchError):
    """Malformed, conflicting, or incomplete provider response."""


@dataclass(frozen=True)
class _MinuteBar:
    start: datetime
    open: float
    high: float
    low: float
    close: float


# Validate provider OHLC fields and convert the provider timestamp into an internal minute bar.
def _parse_minute(row) -> _MinuteBar:
    try:
        if not isinstance(row, dict) or type(row["t"]) is not int or row["t"] % 60000:
            raise ValueError
        prices = [row[field] for field in ("o", "h", "l", "c")]
        if any(type(value) not in (int, float) or not isfinite(value) for value in prices):
            raise ValueError
        o, h, low, c = prices
        if low > min(o, c) or h < max(o, c) or low > h:
            raise ValueError
        start = datetime.fromtimestamp(row["t"] / 1000, timezone.utc).astimezone(NY_TIMEZONE)
        return _MinuteBar(start, o, h, low, c)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise DataError("Invalid minute OHLC or timestamp in Massive response") from None


class MassiveFetcher:
    """Sequential, bounded requests. Reuse one client and close it on shutdown."""

    # Set up credentials, the HTTP connection, the clock, and retry/publication-delay settings.
    def __init__(self, api_key=None, *, session=None, now=None, sleep=time.sleep,
                 delay_seconds=DATA_DELAY_SECONDS, max_attempts=REQUEST_MAX_ATTEMPTS):
        if api_key is None:
            load_environment()
            api_key = require_environment("MASSIVE_API_KEY")["MASSIVE_API_KEY"]
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("MASSIVE_API_KEY is missing")
        if delay_seconds < 0 or max_attempts < 1:
            raise ValueError("Delay must be nonnegative and attempts must be positive")
        self._api_key = api_key.strip()
        self._http = session if session is not None else requests.Session()
        self._owns_session = session is None
        self._now = now or (lambda: datetime.now(NY_TIMEZONE))
        self._sleep = sleep
        self.delay_seconds = delay_seconds
        self.max_attempts = max_attempts

    # Close the HTTP connection if this fetcher created and owns it.
    def close(self):
        if self._owns_session:
            self._http.close()

    # Return this fetcher when it is opened with a Python with block.
    def __enter__(self):
        return self

    # Release the owned HTTP connection when the with block ends, including after an error.
    def __exit__(self, *_):
        self.close()

    # Subtract the configured publication delay from now to determine the latest eligible completion time.
    def _cutoff(self):
        return aware_et(self._now()) - timedelta(seconds=self.delay_seconds)

    # Expose the current completion cutoff so startup uses the same delay as fetching.
    def available_until(self) -> datetime:
        return self._cutoff()

    # Validate the pagination destination and remove any API key embedded in its query string.
    def _safe_url(self, url):
        """Never follow provider pagination to another host or forward its key."""
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.netloc != "api.massive.com"
                or not parts.path.startswith("/v2/aggs/ticker/") or parts.fragment):
            raise DataError("Unexpected Massive pagination URL")
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                 if key.lower() != "apikey"]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))

    # Send an authenticated request and handle retries, timeouts, HTTP failures, and invalid responses.
    def _request(self, url, params=None):
        url = self._safe_url(url)
        for attempt in range(self.max_attempts):
            retry_after = None
            try:
                # Header auth avoids putting the key in request URLs or logs.
                response = self._http.get(
                    url, params=params, headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False,
                )
            except requests.RequestException:
                reason = "network failure"
            else:
                try:
                    status = response.status_code
                    if status in (401, 403):
                        raise AuthenticationError(f"Massive HTTP {status}: check API key and data entitlement")
                    if status == 429 or 500 <= status <= 599:
                        reason = f"HTTP {status}"
                        retry_after = response.headers.get("Retry-After")
                    elif status != 200:
                        raise FetchError(f"Massive HTTP {status}")
                    else:
                        try:
                            payload = response.json()
                        except ValueError:
                            raise DataError("Massive returned invalid JSON") from None
                        if not isinstance(payload, dict) or payload.get("status") != "OK":
                            raise DataError("Massive returned a non-OK or malformed response")
                        return payload
                finally:
                    response.close()
            if attempt + 1 == self.max_attempts:
                raise FetchError(f"Massive {reason} after {self.max_attempts} attempts") from None
            delay = min(2 ** attempt, 30)
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    try:
                        delay = max(delay, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        pass
            if delay > 60:
                raise FetchError("Massive requested a retry delay over 60 seconds; retry this range later")
            LOG.warning("Massive %s; retrying in %.1f seconds", reason, delay)
            self._sleep(delay)

    # Download all pages of a minute-data window, sort the bars, and reject conflicting duplicates.
    def _fetch_minutes(self, ticker, start, end):
        """Fetch a bounded window fully, follow all pages, and reject conflicts."""
        url = (f"{MASSIVE_BASE_URL}/v2/aggs/ticker/{quote(ticker, safe='')}/range/1/minute/"
               f"{int(start.timestamp() * 1000)}/{int(end.timestamp() * 1000) - 1}")
        params = {"adjusted": "true", "sort": "asc", "limit": 50000}
        seen_pages, bars = set(), {}
        for _ in range(1000):
            safe_url = self._safe_url(url)
            if safe_url in seen_pages:
                raise DataError("Massive pagination repeated a page")
            seen_pages.add(safe_url)
            payload = self._request(safe_url, params)
            params = None
            if payload.get("adjusted") is False:
                raise DataError("Massive returned unadjusted data for an adjusted request")
            if payload.get("ticker", ticker) != ticker:
                raise DataError("Massive returned a different ticker")
            rows = payload.get("results", [])
            if (not isinstance(rows, list)
                    or ("resultsCount" in payload and payload["resultsCount"] != len(rows))):
                raise DataError("Massive response is missing expected results")
            for row in rows:
                bar = _parse_minute(row)
                if start <= bar.start and bar.start + MINUTE <= end:
                    old = bars.get(bar.start)
                    if old is not None and old != bar:
                        raise DataError("Conflicting duplicate minute bars; refetch the range")
                    bars[bar.start] = bar
            next_url = payload.get("next_url")
            if not next_url:
                query_count = payload.get("queryCount", 0)
                if type(query_count) is not int or query_count < 0:
                    raise DataError("Invalid Massive query count")
                if query_count >= 50000:
                    raise DataError("Massive hit the base-bar limit without pagination")
                return sorted(bars.values(), key=lambda bar: bar.start)
            if not isinstance(next_url, str):
                raise DataError("Invalid pagination URL")
            url = next_url
        raise DataError("Massive pagination exceeded the page limit")

    # Reuse each minute-data download to build all requested timeframes within regular sessions.
    def fetch_timeframes(self, ticker, timeframes, start, end):
        """Share each minute download across requested timeframes; no disk writes.

        Successful empty intervals are omitted, never forward-filled. A successful
        provider response is assumed complete through the configured cutoff;
        delayed feeds require a matching delay and later correction handling.
        """
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("Ticker must be a nonempty provider symbol")
        timeframes = tuple(dict.fromkeys(timeframes))
        for timeframe in timeframes:
            timeframe_duration(timeframe)
        start, end = aware_et(start), aware_et(end)
        if start >= end:
            raise ValueError("Range end must be after start")
        end = min(end, self._cutoff())
        result = {timeframe: [] for timeframe in timeframes}
        if start >= end or not timeframes:
            return result
        # Seven calendar days stay well below 50,000 source minutes. This bounds
        # intermediate source memory, including when history spans years.
        day = start.date()
        while day <= end.date():
            last_day = min(day + timedelta(days=6), end.date())
            window_sessions = sessions(day, last_day)
            due = {tf: [(left, right) for session in window_sessions
                        for left, right in intervals(session, tf)
                        if left >= start and right <= end] for tf in timeframes}
            all_due = [interval for values in due.values() for interval in values]
            if all_due:
                source_start = min(left for left, _ in all_due)
                source_end = max(right for _, right in all_due)
                source = self._fetch_minutes(ticker, source_start, source_end)
                for tf, windows in due.items():
                    index = 0
                    for left, right in windows:
                        while index < len(source) and source[index].start < left:
                            index += 1
                        first = index
                        while index < len(source) and source[index].start < right:
                            index += 1
                        group = source[first:index]
                        if group:
                            result[tf].append(Candle(
                                symbol=ticker, timeframe=tf, start_time=left, timestamp=right,
                                open=group[0].open, high=max(bar.high for bar in group),
                                low=min(bar.low for bar in group), close=group[-1].close,
                            ))
                        else:
                            LOG.debug("No qualifying trades: %s %s ending %s", ticker, tf, right)
            day = last_day + timedelta(days=1)
        return result

    # Return completed candles whose full intervals fit inside the requested date/time range.
    def fetch_candles(self, ticker: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        return self.fetch_timeframes(ticker, [timeframe], start, end)[timeframe]

    # Return completed candles for today, or an empty list before the open or on a closed day.
    def fetch_today_candles(self, ticker: str, timeframe: str) -> list[Candle]:
        timeframe_duration(timeframe)
        now = aware_et(self._now())
        today = sessions(now.date(), now.date())
        if not today or now <= today[0].open:
            return []
        return self.fetch_candles(ticker, timeframe, today[0].open, min(now, today[0].close))

    # Return today's newest completed candle, or None if no candle is available.
    def fetch_latest_candle(self, ticker: str, timeframe: str) -> Candle | None:
        """Latest completed candle of today's session, or None (no prior-day fallback)."""
        candles = self.fetch_today_candles(ticker, timeframe)
        return candles[-1] if candles else None

    # Search backward for the requested number of completed candles and return them oldest first.
    def fetch_history(self, ticker, timeframe, count=MAX_CANDLES, *, end=None,
                      max_lookback_days=HISTORY_MAX_LOOKBACK_DAYS):
        """Newest count candles, oldest first; bounded search reports partial history.

        Configure lookback to match provider entitlement. Network/auth failures
        raise FetchError rather than returning a misleading partial success.
        """
        timeframe_duration(timeframe)
        if type(count) is not int or count < 1 or max_lookback_days < 1:
            raise ValueError("Count and maximum lookback must be positive")
        stop = min(aware_et(end) if end is not None else self._cutoff(), self._cutoff())
        earliest = datetime.combine(stop.date() - timedelta(days=max_lookback_days), day_time.min, NY_TIMEZONE)
        collected = []
        while stop > earliest and len(collected) < count:
            start = max(earliest, datetime.combine(stop.date() - timedelta(days=6), day_time.min, NY_TIMEZONE))
            if start == stop:
                break
            candles = self.fetch_candles(ticker, timeframe, start, stop)
            collected = (candles + collected)[-count:]
            stop = start
        if len(collected) < count:
            LOG.warning("%s %s: partial history (%d/%d) within %d days", ticker, timeframe, len(collected), count, max_lookback_days)
        return collected


# Open a temporary fetcher, return completed candles whose full intervals fit inside the requested date/time range, then close it.
def fetch_candles(ticker, timeframe, start, end):
    with MassiveFetcher() as client:
        return client.fetch_candles(ticker, timeframe, start, end)


# Open a temporary fetcher, return completed candles for today, or an empty list before the open or on a closed day, then close it.
def fetch_today_candles(ticker, timeframe):
    with MassiveFetcher() as client:
        return client.fetch_today_candles(ticker, timeframe)


# Open a temporary fetcher, return today's newest completed candle, or None if no candle is available, then close it.
def fetch_latest_candle(ticker, timeframe):
    with MassiveFetcher() as client:
        return client.fetch_latest_candle(ticker, timeframe)


# Open a temporary fetcher, search backward for the requested number of completed candles and return them oldest first, then close it.
def fetch_history(ticker, timeframe, count=MAX_CANDLES, **kwargs):
    with MassiveFetcher() as client:
        return client.fetch_history(ticker, timeframe, count, **kwargs)

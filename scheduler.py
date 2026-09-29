# File purpose: Fetch due completed candles and save their OHLC and SMA hits in order.

import logging
import time
from datetime import datetime, time as day_time, timedelta
from threading import Event

from candle import Candle
from candle_buffer import CandleBuffer
from config import NY_TIMEZONE, RANKING_REPORT_SECONDS, SCHEDULER_POLL_SECONDS, SCHEDULER_RETRY_SECONDS
from fetcher import FetchError, MassiveFetcher
from hit_detector import detect_hits
from market_calendar import aware_et, intervals, sessions
from sma import calculate_smas
from ranking import OutfitRankings
from storage.influx import InfluxStorage, StorageError

LOG = logging.getLogger(__name__)


class Scheduler:
    # Select successfully initialized pairs and remember where live tracking begins.
    def __init__(
        self,
        buffers: dict[tuple[str, str], CandleBuffer],
        statuses: dict[tuple[str, str], str],
        storage: InfluxStorage,
        fetcher: MassiveFetcher,
        *,
        start: datetime,
        rankings: OutfitRankings | None = None,
        resume_times: dict[tuple[str, str], datetime] | None = None,
    ):
        self.buffers = buffers
        self.storage = storage
        self.fetcher = fetcher
        self.rankings = rankings if rankings is not None else OutfitRankings()
        self._stop = Event()
        self._covered_until = {}
        self._retry_at = {}
        start = aware_et(start)

        for key, buffer in buffers.items():
            if statuses.get(key) not in ("READY", "PARTIAL", "EMPTY"):
                LOG.warning("Skipping uninitialized or failed pair: %s %s", *key)
                continue
            latest = buffer.latest()
            # Keep a separate retrieval cursor: an interval with no trades has no
            # candle, but a successful fetch can still cover that interval.
            if resume_times is not None:
                if key not in resume_times:
                    raise ValueError("Active pair has no durable resume time")
                self._covered_until[key] = aware_et(resume_times[key])
            else:
                self._covered_until[key] = latest.timestamp if latest else start

    # Save processing progress only after the associated candle and hit writes have succeeded.
    def _checkpoint(self, key, timestamp, buffer) -> None:
        latest = buffer.latest()
        self.storage.save_checkpoint(*key, timestamp, buffer.size(), latest.timestamp if latest else None)

    # Find the last eligible interval end in one bounded catch-up window.
    def _due_end(self, timeframe: str, start: datetime, end: datetime) -> datetime | None:
        due = None
        for session in sessions(start.date(), end.date()):
            for left, right in intervals(session, timeframe):
                if left >= start and right <= end:
                    due = right
        return due

    # Save a candle, its hits, and its checkpoint before updating rankings and active RAM.
    def _process_candle(self, key: tuple[str, str], candle: Candle) -> bool:
        buffer = self.buffers[key]
        latest = buffer.latest()
        if latest is not None and candle.timestamp <= latest.timestamp:
            return False

        candidate = buffer.copy()
        candidate.add(candle)
        hits = detect_hits(candle, calculate_smas(candidate.closes()))
        self.storage.save_candle(candle)
        self.storage.save_hits(hits)
        self._checkpoint(key, candle.timestamp, candidate)
        self.rankings.add_hits(hits)
        self.buffers[key] = candidate
        self._covered_until[key] = candle.timestamp
        LOG.info("Processed %s %s ending %s: %d hits", *key, candle.timestamp.isoformat(), len(hits))
        return True

    # Fetch only due pairs, processing every returned candle chronologically; return the count processed.
    def run_once(self) -> int:
        cutoff = self.fetcher.available_until()
        processed = 0
        for key, cursor in self._covered_until.items():
            if self._stop.is_set():
                break
            if time.monotonic() < self._retry_at.get(key, 0) or cursor >= cutoff:
                continue

            symbol, timeframe = key
            # A long outage is handled in bounded windows. Midnight window ends
            # avoid cutting through an intraday candle.
            window_end = min(
                cutoff,
                datetime.combine(cursor.date() + timedelta(days=7), day_time.min, NY_TIMEZONE),
            )
            due_end = self._due_end(timeframe, cursor, window_end)
            if due_end is None:
                # Advance across wholly elapsed windows with no eligible bars,
                # but never move past the start of an unfinished live interval.
                if window_end < cutoff:
                    try:
                        self._checkpoint(key, window_end, self.buffers[key])
                        self._covered_until[key] = window_end
                    except StorageError:
                        self._retry_at[key] = time.monotonic() + SCHEDULER_RETRY_SECONDS
                        LOG.error("%s %s: failed to save empty-window progress", *key)
                continue

            try:
                candles = self.fetcher.fetch_candles(symbol, timeframe, cursor, due_end)
                for candle in candles:
                    if self._stop.is_set():
                        return processed
                    processed += self._process_candle(key, candle)
                # Successful empty intervals count as covered, not as invented
                # candles. A fetch/write failure must never advance this cursor.
                if self._covered_until[key] < due_end:
                    self._checkpoint(key, due_end, self.buffers[key])
                    self._covered_until[key] = due_end
                self._retry_at.pop(key, None)
            except (FetchError, StorageError, ValueError) as error:
                self._retry_at[key] = time.monotonic() + SCHEDULER_RETRY_SECONDS
                LOG.error("%s %s processing failed (%s); retry scheduled", *key, type(error).__name__)
        return processed

    # Check for due work periodically until stop() is called or Ctrl+C is pressed.
    def run_forever(self) -> None:
        if not self._covered_until:
            LOG.warning("Scheduler has no initialized pairs to process")
            return
        LOG.info("Scheduler started for %d ticker/timeframe pairs", len(self._covered_until))
        next_report = 0
        try:
            while not self._stop.is_set():
                self.run_once()
                if time.monotonic() >= next_report:
                    self.rankings.log_top()
                    next_report = time.monotonic() + RANKING_REPORT_SECONDS
                self._stop.wait(SCHEDULER_POLL_SECONDS)
        except KeyboardInterrupt:
            self.stop()
        finally:
            LOG.info("Scheduler stopped")

    # Request a clean stop between requests or candles and interrupt the polling wait.
    def stop(self) -> None:
        self._stop.set()

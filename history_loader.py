# File purpose: Restore candle history from InfluxDB, fetch missing data, and fill RAM buffers.

import logging
from datetime import datetime, time, timedelta

from candle_buffer import CandleBuffer
from config import MAX_CANDLES, NY_TIMEZONE
from fetcher import FetchError, MassiveFetcher
from market_calendar import aware_et
from storage.influx import InfluxStorage, StorageError

LOG = logging.getLogger(__name__)


# Build one current buffer, saving fetched candles before returning it to the caller.
def load_history(
    symbol: str,
    timeframe: str,
    storage: InfluxStorage,
    fetcher: MassiveFetcher,
    *,
    end: datetime | None = None,
    max_size: int = MAX_CANDLES,
) -> CandleBuffer:
    """Warm-up history only: this does not detect or replay historical SMA hits."""
    cutoff = fetcher.available_until()
    if end is not None:
        cutoff = min(aware_et(end), cutoff)

    buffer = CandleBuffer(max_size, symbol=symbol, timeframe=timeframe)
    stored = storage.load_latest_candles(symbol, timeframe, limit=max_size, end=cutoff)
    buffer.extend(stored)
    LOG.info("%s %s: restored %d candles from InfluxDB", symbol, timeframe, buffer.size())

    # A full buffer can still be stale. Retrieve every newer interval in bounded
    # windows, ending at midnight so a window never splits a trading-session bar.
    if buffer.latest() is not None:
        cursor = buffer.latest().timestamp
        while cursor < cutoff:
            window_end = min(
                cutoff,
                datetime.combine(cursor.date() + timedelta(days=7), time.min, NY_TIMEZONE),
            )
            newer = fetcher.fetch_candles(symbol, timeframe, cursor, window_end)
            candidate = buffer.copy()
            candidate.extend(newer)
            storage.save_candles(newer)
            buffer = candidate
            cursor = window_end

    # After catching up, request only the remaining older candle count. With no
    # stored history, this requests the latest max_size candles through cutoff.
    missing = max_size - buffer.size()
    if missing:
        history_end = buffer.candles[0].start_time if buffer.size() else cutoff
        LOG.info("%s %s: requesting %d older candles", symbol, timeframe, missing)
        older = fetcher.fetch_history(symbol, timeframe, count=missing, end=history_end)
        candidate = CandleBuffer(max_size, symbol=symbol, timeframe=timeframe)
        candidate.extend(older)
        candidate.extend(buffer.candles)
        storage.save_candles(older)
        buffer = candidate

    return buffer


# Fill the requested buffers independently and return each pair's readiness status.
def initialize_history(
    buffers: dict[tuple[str, str], CandleBuffer],
    storage: InfluxStorage,
    fetcher: MassiveFetcher,
    *,
    end: datetime | None = None,
) -> dict[tuple[str, str], str]:
    """READY = full, PARTIAL = some history, EMPTY = none, FAILED = load error.

    Existing buffer entries are replaced only after that pair loads successfully.
    A FAILED entry must not be used for live processing, even if it held old data.
    """
    cutoff = fetcher.available_until()
    if end is not None:
        cutoff = min(aware_et(end), cutoff)
    statuses = {}
    for (symbol, timeframe), previous in buffers.items():
        key = (symbol, timeframe)
        try:
            loaded = load_history(
                symbol, timeframe, storage, fetcher,
                end=cutoff, max_size=previous.max_size,
            )
        except (FetchError, StorageError, ValueError) as error:
            statuses[key] = "FAILED"
            LOG.error("%s %s: history initialization failed (%s)", symbol, timeframe, type(error).__name__)
            continue

        buffers[key] = loaded
        status = "READY" if loaded.size() == loaded.max_size else "PARTIAL"
        if loaded.size() == 0:
            status = "EMPTY"
        statuses[key] = status
        LOG.info("%s %s: %d/%d candles %s", symbol, timeframe, loaded.size(), loaded.max_size, status)
    return statuses

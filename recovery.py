# File purpose: Prepare first-start history or restore exact checkpoint buffers for missed-candle replay.

import logging
from datetime import datetime, timedelta

from candle_buffer import CandleBuffer
from fetcher import FetchError
from history_loader import load_history
from market_calendar import intervals, sessions
from storage.influx import StorageError

LOG = logging.getLogger(__name__)


# Find a completed interval boundary so startup never skips part of the next live candle.
def tracking_boundary(timeframe: str, cutoff: datetime) -> datetime:
    for session in reversed(sessions(cutoff.date() - timedelta(days=30), cutoff.date())):
        completed = [right for _, right in intervals(session, timeframe) if right <= cutoff]
        if completed:
            return completed[-1]
    raise ValueError("No recent completed trading interval for the startup baseline")


# Restore checkpoint buffers exactly, or establish a saved warm-up baseline for new pairs.
def prepare_startup(buffers, storage, fetcher, checkpoints, hit_summaries):
    cutoff = fetcher.available_until()
    pairs_with_hits = {(row["symbol"], row["timeframe"]) for row in hit_summaries}
    statuses = {}
    resume_times = {}
    for key, previous in buffers.items():
        symbol, timeframe = key
        try:
            checkpoint = checkpoints.get(key)
            if checkpoint is not None:
                boundary = checkpoint["timestamp"]
                if boundary > cutoff:
                    raise ValueError("Checkpoint is ahead of the current data cutoff")
                count = checkpoint["buffer_count"]
                restored = CandleBuffer(previous.max_size, symbol=symbol, timeframe=timeframe)
                if count:
                    stored = storage.load_latest_candles(symbol, timeframe, limit=count, end=boundary)
                    restored.extend(stored)
                latest = restored.latest()
                last_time = latest.timestamp if latest else None
                # Preserve partial-history SMA readiness exactly as it was before
                # the crash. Adding extra older candles would change replay hits.
                if restored.size() != count or last_time != checkpoint["last_candle_time"]:
                    raise ValueError("Checkpoint history is missing; restore database history before replay")
            else:
                if key in pairs_with_hits:
                    raise ValueError("Saved hits lack a checkpoint; migration is required before tracking")
                boundary = tracking_boundary(timeframe, cutoff)
                restored = load_history(symbol, timeframe, storage, fetcher,
                                        end=boundary, max_size=previous.max_size)
                latest = restored.latest()
                storage.save_checkpoint(symbol, timeframe, boundary, restored.size(),
                                        latest.timestamp if latest else None)

            buffers[key] = restored
            resume_times[key] = boundary
            status = "READY" if restored.size() == restored.max_size else "PARTIAL"
            statuses[key] = status if restored.size() else "EMPTY"
            LOG.info("%s %s: %s, %d candles, resume after %s",
                     symbol, timeframe, statuses[key], restored.size(), boundary.isoformat())
        except (FetchError, StorageError, ValueError) as error:
            statuses[key] = "FAILED"
            LOG.error("%s %s startup failed: %s", symbol, timeframe, error)
    return statuses, resume_times

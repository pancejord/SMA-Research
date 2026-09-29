# File purpose: Preload up to 999 completed candles per ticker/timeframe from Massive into InfluxDB.

import argparse
import logging
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

# Reuse the main project's configuration and data rules when launched from this folder.
PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from candle_buffer import CandleBuffer
from config import (
    HISTORY_MAX_LOOKBACK_DAYS, LOG_LEVEL, MAX_CANDLES, NY_TIMEZONE, TICKERS,
    load_environment, require_environment, validate_config,
)
from fetcher import FetchError, MassiveFetcher
from storage.influx import InfluxStorage, StorageError
from timeframes import TIMEFRAMES

LOG = logging.getLogger(__name__)


# Read optional ticker/timeframe selections and the maximum historical search depth.
def parse_arguments():
    parser = argparse.ArgumentParser(description="Fetch 999 candles per pair and preload InfluxDB.")
    parser.add_argument("--tickers", nargs="+", choices=TICKERS, help="Default: all configured tickers")
    parser.add_argument("--timeframes", nargs="+", choices=TIMEFRAMES, help="Default: all configured timeframes")
    parser.add_argument("--lookback-days", type=int, default=HISTORY_MAX_LOOKBACK_DAYS,
                        help="Maximum calendar days to search; match this to your data-plan access")
    return parser.parse_args()


# Validate a completed history batch in RAM and save it using the main application's OHLC schema.
def save_history(symbol, timeframe, candles, storage):
    buffer = CandleBuffer(symbol=symbol, timeframe=timeframe)
    buffer.extend(candles)
    storage.save_candles(buffer.candles)
    status = "READY" if buffer.size() == MAX_CANDLES else "PARTIAL"
    if not buffer.size():
        status = "EMPTY"
    LOG.info("%s %s: saved %d/%d candles %s", symbol, timeframe, buffer.size(), MAX_CANDLES, status)


# Search backward for one ticker, sharing each minute download across all unfinished timeframes.
def preload_ticker(symbol, timeframes, cutoff, lookback_days, storage, fetcher):
    histories = {timeframe: [] for timeframe in timeframes}
    counts = {}
    earliest = datetime.combine(cutoff.date() - timedelta(days=lookback_days), time.min, NY_TIMEZONE)
    stop = cutoff

    while histories and stop > earliest:
        # Midnight boundaries keep sessions intact. Source data is limited to
        # small date windows, and each target history holds at most 999 candles.
        start = max(earliest, datetime.combine(stop.date() - timedelta(days=6), time.min, NY_TIMEZONE))
        fetched = fetcher.fetch_timeframes(symbol, histories, start, stop)
        for timeframe in list(histories):
            missing = MAX_CANDLES - len(histories[timeframe])
            # We are moving backward; prepend older candles to preserve order.
            histories[timeframe] = fetched[timeframe][-missing:] + histories[timeframe]
            if len(histories[timeframe]) == MAX_CANDLES:
                save_history(symbol, timeframe, histories[timeframe], storage)
                counts[timeframe] = MAX_CANDLES
                del histories[timeframe]
        stop = start

    # New or thinly traded symbols may have insufficient history. Save what is
    # available and report the shortfall rather than manufacturing candles.
    for timeframe, candles in histories.items():
        save_history(symbol, timeframe, candles, storage)
        counts[timeframe] = len(candles)
    return counts


# Preload selected pairs, without starting the scheduler or calculating any SMA hits.
def main() -> int:
    args = parse_arguments()
    logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.lookback_days < 1:
            raise ValueError("--lookback-days must be positive")
        load_environment()
        validate_config()
        require_environment("MASSIVE_API_KEY", "INFLUX_URL", "INFLUX_TOKEN", "INFLUX_ORG", "INFLUX_BUCKET")
        tickers = list(dict.fromkeys(args.tickers or TICKERS))
        timeframes = list(dict.fromkeys(args.timeframes or TIMEFRAMES))
        ready = partial = skipped = failures = 0

        with InfluxStorage() as storage, MassiveFetcher() as fetcher:
            storage.check_connection()
            checkpoints = storage.load_checkpoints()
            cutoff = fetcher.available_until()
            LOG.info("Preloading %d tickers and %d timeframes through %s", len(tickers), len(timeframes), cutoff.isoformat())
            for symbol in tickers:
                selected = []
                for timeframe in timeframes:
                    # A tracked pair must resume at its checkpoint through main.py;
                    # overwriting its earlier history could alter recovery SMAs.
                    if (symbol, timeframe) in checkpoints:
                        LOG.info("%s %s: already tracked; leave history to main.py recovery", symbol, timeframe)
                        skipped += 1
                    else:
                        selected.append(timeframe)
                if not selected:
                    continue
                try:
                    counts = preload_ticker(symbol, selected, cutoff, args.lookback_days, storage, fetcher)
                    ready += sum(count == MAX_CANDLES for count in counts.values())
                    partial += sum(count < MAX_CANDLES for count in counts.values())
                except (FetchError, StorageError, ValueError) as error:
                    failures += 1
                    LOG.error("%s preload interrupted: %s. Earlier acknowledged writes remain saved.", symbol, error)
            LOG.info("Preload complete: %d full pairs, %d partial/empty pairs, %d tracked pairs skipped, %d interrupted tickers",
                     ready, partial, skipped, failures)
            if failures:
                LOG.info("Final pair totals exclude interrupted tickers; see their individual save messages.")
            return 1 if failures or partial else 0
    except KeyboardInterrupt:
        LOG.info("Preload stopped; acknowledged InfluxDB writes remain saved")
        return 130
    except (FetchError, StorageError, ValueError) as error:
        LOG.error("Preload stopped: %s", error)
        return 1
    except Exception as error:
        LOG.error("Preload stopped with %s", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

# File purpose: Start history/recovery, restore rankings, and run the SMA candle-processing application.

import argparse
import logging

from candle_buffer import initialize_buffers
from config import (
    LOG_LEVEL, SAVE_OHLC, SAVE_SMA_HITS, TICKERS,
    load_environment, require_environment, validate_config,
)
from fetcher import FetchError, MassiveFetcher
from ranking import OutfitRankings
from recovery import prepare_startup
from scheduler import Scheduler
from storage.influx import InfluxStorage, StorageError
from timeframes import TIMEFRAMES

LOG = logging.getLogger(__name__)


# Read optional ticker/timeframe selections and a one-pass operating mode.
def parse_arguments():
    parser = argparse.ArgumentParser(description="Collect OHLC candles, detect SMA hits, and rank outfits.")
    parser.add_argument("--tickers", nargs="+", choices=TICKERS, help="Default: all configured tickers")
    parser.add_argument("--timeframes", nargs="+", choices=TIMEFRAMES, help="Default: all configured timeframes")
    parser.add_argument("--once", action="store_true", help="Initialize, run one bounded processing pass, then exit")
    return parser.parse_args()


# Connect the existing modules; calculation and database details stay in their own files.
def main() -> int:
    args = parse_arguments()
    logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
    try:
        load_environment()
        validate_config()
        require_environment("MASSIVE_API_KEY", "INFLUX_URL", "INFLUX_TOKEN", "INFLUX_ORG", "INFLUX_BUCKET")
        if not SAVE_OHLC or not SAVE_SMA_HITS:
            raise ValueError("Durable processing requires SAVE_OHLC and SAVE_SMA_HITS enabled")

        buffers = initialize_buffers(args.tickers, args.timeframes)
        LOG.info("Starting SMA engine for %d ticker/timeframe pairs", len(buffers))
        with InfluxStorage() as storage, MassiveFetcher() as fetcher:
            storage.check_connection()
            checkpoints = storage.load_checkpoints()
            summaries = storage.load_hit_summaries()
            statuses, resume_times = prepare_startup(buffers, storage, fetcher, checkpoints, summaries)
            active = len(resume_times)
            LOG.info("Startup finished: %d active pairs, %d failed pairs", active, len(buffers) - active)
            if not active:
                return 1

            rankings = OutfitRankings()
            rankings.restore(summaries)
            scheduler = Scheduler(
                buffers, statuses, storage, fetcher, start=fetcher.available_until(),
                rankings=rankings, resume_times=resume_times,
            )
            if args.once:
                processed = scheduler.run_once()
                LOG.info("One pass finished: %d candles processed; this does not guarantee catch-up is complete", processed)
            else:
                scheduler.run_forever()
            rankings.log_top()
        return 0
    except KeyboardInterrupt:
        LOG.info("Shutdown requested")
        return 0
    except (ValueError, FetchError, StorageError) as error:
        LOG.error("Application stopped: %s", error)
        return 1
    except Exception as error:
        # Raw client errors can include request details, so report the type only.
        LOG.error("Unexpected %s; application stopped. Restart will use saved checkpoints.", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

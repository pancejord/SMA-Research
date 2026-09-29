# File purpose: Runs a small manual Massive download check without writing to InfluxDB.
"""Small live API check. No database writes or continuous collection."""

import argparse
import logging
from datetime import date, datetime, timedelta

from config import NY_TIMEZONE
from fetcher import FetchError, MassiveFetcher
from market_calendar import sessions
from timeframes import TIMEFRAMES


# Read command-line options, fetch a small candle sample, and report results or a safe error.
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--date", type=date.fromisoformat, help="YYYY-MM-DD; default: latest fully closed session")
    parser.add_argument("--timeframe", choices=TIMEFRAMES, default="5m")
    parser.add_argument("--count", type=int, help="Fetch this many historical candles instead of a single session")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        with MassiveFetcher() as client:
            if args.date:
                available = sessions(args.date, args.date)
            else:
                today = datetime.now(NY_TIMEZONE).date()
                available = tuple(s for s in sessions(today - timedelta(days=14), today)
                                  if s.close <= datetime.now(NY_TIMEZONE) - timedelta(seconds=client.delay_seconds))
            if not available:
                print("No completed trading session in the selected date range.")
                return 0
            session = available[-1]
            if args.count is not None:
                bars = client.fetch_history(args.ticker, args.timeframe, args.count, end=session.close)
            else:
                bars = client.fetch_candles(args.ticker, args.timeframe, session.open, session.close)
            print(f"{args.ticker} {args.timeframe}: {len(bars)} candles")
            for label, candle in (("First", bars[0]), ("Last", bars[-1])) if bars else ():
                print(f"{label}: {candle.start_time.isoformat()} -> {candle.timestamp.isoformat()} "
                      f"O={candle.open} H={candle.high} L={candle.low} C={candle.close}")
            print("No InfluxDB writes were performed.")
            return 0
    except (FetchError, ValueError) as error:
        print(f"Check failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

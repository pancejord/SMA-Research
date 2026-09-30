# File purpose: Report top outfit/ticker/timeframe combinations over 2–20 completed trading sessions.

import argparse
from datetime import date, datetime, time, timedelta

from config import NY_TIMEZONE, RESEARCH_VERSION, TOP_N_OUTFITS
from market_calendar import aware_et, sessions
from ranking import OutfitRankings
from storage.influx import InfluxStorage, StorageError
from timeframes import TIMEFRAMES


# Find the most recent completed trading sessions, excluding weekends, holidays, and today's partial session.
def completed_sessions(count: int, as_of: datetime):
    if type(count) is not int or not 2 <= count <= 20:
        raise ValueError("Trading-day count must be between 2 and 20")
    as_of = aware_et(as_of)
    # A year easily covers these short windows; fail clearly if the calendar has no coverage.
    available = [session for session in sessions(as_of.date() - timedelta(days=366), as_of.date())
                 if session.close <= as_of]
    if len(available) < count:
        raise ValueError("Not enough completed sessions in the calendar")
    return available[-count:]


# Build an independent historical ranking without changing the live scheduler's counters.
def query_rankings(storage, days: int, as_of: datetime, *, limit=TOP_N_OUTFITS,
                   symbol: str | None = None, timeframe: str | None = None):
    selected = completed_sessions(days, as_of)
    rankings = OutfitRankings()
    rankings.restore(storage.load_hit_summaries(start=selected[0].open, end=selected[-1].close))
    return selected[0].open, selected[-1].close, rankings.top(limit, symbol=symbol, timeframe=timeframe)


# Select one or more trading-day windows, an optional historical end date, and ranking filters.
def parse_arguments():
    parser = argparse.ArgumentParser(description="Read InfluxDB outfit rankings by completed trading days.")
    parser.add_argument("--days", type=int, nargs="+", choices=range(2, 21), default=list(range(2, 21)),
                        help="Default: every window from 2 through 20 trading days")
    parser.add_argument("--through", type=date.fromisoformat, help="Last date to consider, YYYY-MM-DD")
    parser.add_argument("--top", type=int, default=TOP_N_OUTFITS)
    parser.add_argument("--ticker", help="Optional ticker filter; ticker/timeframe results stay separate")
    parser.add_argument("--timeframe", choices=TIMEFRAMES)
    return parser.parse_args()


# Query stored hits and print the top combinations for each selected window; never fetch or write data.
def main() -> int:
    args = parse_arguments()
    try:
        if args.top < 1:
            raise ValueError("--top must be positive")
        now = datetime.now(NY_TIMEZONE)
        if args.through is not None and args.through > now.date():
            raise ValueError("--through cannot be a future date")
        as_of = min(now, datetime.combine(args.through, time.max, NY_TIMEZONE)) if args.through else now
        print(f"Research version: {RESEARCH_VERSION}. Completed trading sessions only.")
        print("Counts reflect stored hits; a full calendar window does not guarantee complete collected data.")
        with InfluxStorage() as storage:
            for days in sorted(set(args.days)):
                first, last, rows = query_rankings(
                    storage, days, as_of, limit=args.top, symbol=args.ticker, timeframe=args.timeframe,
                )
                print(f"\n{days} trading days | {first.isoformat()} through {last.isoformat()}")
                print("Rank | Outfit | Ticker | Timeframe | Hits | Latest hit")
                for position, row in enumerate(rows, 1):
                    print(f"{position} | {row.outfit} | {row.symbol} | {row.timeframe} | "
                          f"{row.hit_count} | {row.last_hit_timestamp.isoformat()}")
                if not rows:
                    print("No matching stored hits for this window and filters.")
        return 0
    except (ValueError, StorageError) as error:
        print(f"Report failed: {error}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

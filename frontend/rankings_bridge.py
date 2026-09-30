# File purpose: Return read-only InfluxDB rankings as JSON for the local Next.js server.

import json
import os
import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Query the shared ranking code and return safe errors without printing credential values.
def build_report(options):
    try:
        from config import NY_TIMEZONE, RESEARCH_VERSION, load_environment
        load_environment()
        required = ("INFLUX_URL", "INFLUX_TOKEN", "INFLUX_ORG", "INFLUX_BUCKET")
        missing = [name for name in required if not os.getenv(name, "").strip()]
        if missing:
            return {"kind": "setup", "error": "Configure these settings in Research/.env: " + ", ".join(missing)}

        from query_rankings import query_rankings
        from storage.influx import InfluxStorage, StorageError
        now = datetime.now(NY_TIMEZONE)
        through = date.fromisoformat(options["through"]) if options["through"] else None
        if through is not None and through > now.date():
            return {"kind": "invalid", "error": "The end date cannot be in the future."}
        as_of = min(now, datetime.combine(through, time.max, NY_TIMEZONE)) if through else now
        with InfluxStorage() as storage:
            first, last, rows = query_rankings(
                storage, options["days"], as_of, limit=options["top"],
                symbol=options["ticker"] or None, timeframe=options["timeframe"] or None,
            )
        return {
            "days": options["days"], "start": first.isoformat(), "end": last.isoformat(),
            "version": RESEARCH_VERSION, "generated_at": datetime.now(NY_TIMEZONE).isoformat(),
            "rows": [{"outfit": row.outfit, "ticker": row.symbol, "timeframe": row.timeframe,
                      "hits": row.hit_count, "last_hit": row.last_hit_timestamp.isoformat()} for row in rows],
        }
    except ModuleNotFoundError:
        return {"kind": "setup", "error": "Install the project's Python requirements in Research/.venv first."}
    except ValueError:
        return {"kind": "invalid", "error": "Check the date, trading-day range, and server configuration."}
    except Exception:
        return {"kind": "database", "error": "Unable to read rankings. Check InfluxDB availability, v2/Flux support, and bucket read permission."}


# Read validated filter options from the server and emit one JSON response.
def main():
    report = build_report(json.loads(sys.argv[1]))
    print(json.dumps(report))


if __name__ == "__main__":
    main()

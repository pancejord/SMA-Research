# SMA outfit research

Collect completed regular-session OHLC candles, calculate closing-price SMAs,
store timestamped candles and matching hits in InfluxDB, and rank outfits by hits.

## Current status

Phases 1–10 have implementation code, connected through `main.py`, including
durable progress records and restart replay. Phases 3–10 were not tested, as
requested. Phase 2
passes offline tests; the first live SPY request on September 24 returned HTTP 401,
so provider-price verification is still pending a working Massive credential.
The storage code has not been connected to a database. End-to-end validation,
real-data alignment checks, and recovery testing remain pending. No continuous
collection is running yet. Use the Phase 10 commands below as the application
entry point; earlier phase examples illustrate individual modules only.

`config.py` remains the single source for tickers, outfits, and settings.
`tickers.py` and `outfits.py` re-export these values for the original module layout.
`timeframes.py` defines 59 durations. `candle.py` defines an immutable Candle with
aware ET start/end times and OHLC. Volume is intentionally omitted. Its `timestamp`
is the candle end.

999 completed candles support all configured SMAs for the newest candle. Each
SMA will include that candle's close. Match each OHLC field using
`round(price, 2) == round(sma, 2)`. Keep shortened final-session candles. Calendar
and provider alignment validation are still required; time-of-day settings alone
do not implement holidays or early closes. Phase 2's `market_calendar.py` now uses
the NYSE calendar for these sessions; real provider-price comparison is pending.

## Historical rankings: 2–20 trading days

For a browser interface, see [`frontend/README.md`](frontend/README.md). Start it
with `cd frontend` followed by `npm run dev`, then open `http://127.0.0.1:3000`.
The dashboard provides trading-day, ticker, timeframe, and end-date filters and
reads the same stored ranking data as the terminal command below.

`query_rankings.py` queries InfluxDB for the highest-hit **outfit/ticker/timeframe
combinations**, with a separate leaderboard for each requested rolling window.
It reuses the exchange calendar to skip holidays and weekends. Early-close days
count as one trading day. Windows use the latest **completed sessions**: during
today's trading session, the report ends at the previous completed session.
After today's close it includes today; collection or processing may still lag.

```powershell
# Every rolling window: last 2, last 3, ... last 20 completed trading days.
.\.venv\Scripts\python.exe query_rankings.py

# Selected windows, top 10 distinct outfit/ticker/timeframe combinations per window.
.\.venv\Scripts\python.exe query_rankings.py --days 2 5 10 20 --top 10

# Restrict the results to one ticker and timeframe.
.\.venv\Scripts\python.exe query_rankings.py --days 5 --ticker NVDA --timeframe 33m

# Use the last completed session on or before a historical date.
.\.venv\Scripts\python.exe query_rankings.py --days 20 --through 2026-09-29
```

Each report prints its actual ET start/end timestamps and the rank, outfit,
ticker, timeframe, hit count, and latest hit. The final session-close candle is
included. Counts use saved outfit memberships and the active `RESEARCH_VERSION`.
Two matching OHLC fields still count as two physical hits. Ties sort by latest
hit, then name. Zero-hit combinations are omitted; no results are reported clearly.

These are overlapping rolling windows, not disjoint two-day or twenty-day buckets.
Missing collection days are not replaced with earlier days containing hits.
Reports reflect available stored data; an N-session window does not prove that
collection covered all N sessions. Database retention and collection delays can
reduce the available counts.

This is a read-only reporting command: it needs InfluxDB credentials with read
permission, but no Massive key. It does not fetch candles, write data, or modify
live ranking counters. The default runs 19 summary queries; request fewer windows
with `--days` when desired. Tests and live queries have not been run.

## Setup (PowerShell, Python 3.10+)

For a separate history download before starting the collector, see
[`preload/README.md`](preload/README.md). The utility saves up to 999 candles per
pair to InfluxDB; `main.py` then loads its own RAM buffers from that history.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe check_foundation.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The foundation was verified with Python 3.14.6. `tzdata` supplies timezone data on
Windows; `python-dotenv` loads the project `.env` regardless of the working directory.
Existing process environment values take precedence. Imports do not load secrets
or contact external services. Entry points call `load_environment()` explicitly.

Keep the existing `.env`. If setting up a new computer without one, use
`.env.example` as the template and enter credentials locally. Integration modules
will call `require_environment(...)` for their specific variables. The offline
foundation check does not verify credentials or network connectivity.

## Phase 2 usage

Run a small live check after configuring `MASSIVE_API_KEY` locally in `.env`:

```powershell
.\.venv\Scripts\python.exe check_fetcher.py --ticker SPY --timeframe 33m
.\.venv\Scripts\python.exe check_fetcher.py --ticker SPY --timeframe 5m --count 999
```

The default date is the last fully closed session. Supply `--date YYYY-MM-DD` to
select a date. These commands only read Massive; they do not write InfluxDB.

The public functions in `fetcher.py` are `fetch_candles`, `fetch_today_candles`,
`fetch_latest_candle`, and `fetch_history`. Use a reusable `MassiveFetcher` context
manager for multiple requests. Its `fetch_timeframes(ticker, timeframes, start,
end)` downloads each source window once for all requested timeframes.

```python
from datetime import datetime
from config import NY_TIMEZONE
from fetcher import MassiveFetcher
from timeframes import TIMEFRAMES

with MassiveFetcher() as client:
    candles = client.fetch_timeframes(
        "SPY", TIMEFRAMES,
        datetime(2026, 9, 23, 9, 30, tzinfo=NY_TIMEZONE),
        datetime(2026, 9, 23, 16, 0, tzinfo=NY_TIMEZONE),
    )
```

### Data contract and limits

- Uses split-adjusted Massive **one-minute** OHLC aggregates, grouped locally into
  session-open-anchored intervals. Provider hourly snapping does not guarantee
  09:30 alignment. Volume and VWAP are ignored.
- Range inputs must be aware datetimes. Returns only whole intervals whose start
  is at or after `start` and whose completion is at or before `end` and the current
  availability cutoff. For catch-up, pass the previous candle's end as `start`.
- `DATA_DELAY_SECONDS=60` is the initial publication buffer. Increase it to match
  a delayed subscription. Time eligibility does not guarantee feed finality;
  provider corrections remain later work. Restart replay is now connected in Phase 10.
- Calendar holidays, early closes, DST, and shortened final bars are handled.
  Extended-hours source minutes are excluded. No-trade intervals are omitted;
  no synthetic candles are created. A successful source response is assumed to
  contain all qualifying trades through its requested cutoff.
- `fetch_latest_candle` returns today's latest eligible candle or `None`; holidays
  and pre-open do not fall back to yesterday. Use history for prior sessions.
- History searches backward in bounded windows and keeps only the requested
  count. The default lookback limit is 3,650 calendar days; configure it to match
  your subscription. Partial history is returned with a warning if that limit is
  reached. Fetch failures raise `FetchError`, never a misleading empty success.
- Timeouts, 429, and server errors retry up to three attempts. Authentication and
  malformed-data errors fail clearly. Long provider retry delays are surfaced to
  the caller instead of blocking indefinitely. No request URL contains the key.
- Stock endpoint symbol mappings and index entitlements remain to be validated.
  The supplied ticker universe is unchanged.

Provider references: [Custom bars](https://www.massive.com/docs/rest/stocks/aggregates/custom-bars),
[snapping rules](https://www.massive.com/blog/aggs-api-updates),
[calendar usage](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html).

## Phase 3: in-memory candle buffers

`candle_buffer.py` holds each ticker/timeframe independently, retaining up to 999
completed candles in chronological order. Appending a new candle to a full buffer
automatically drops the oldest. Closing prices retain their original precision.

```python
from candle_buffer import initialize_buffers

buffers = initialize_buffers()  # Empty buffers for all configured pairs; no API call.
buffer = buffers[("NVDA", "33m")]
# buffer.extend(history)        # Oldest-first Candle objects from the history loader.
# added = buffer.add(candle)    # True for a new candle; False for an identical replay.
latest = buffer.latest()       # None until candles have been loaded.
closes = buffer.closes()       # Oldest to newest; SMA 44 will use closes[-44:].
available = buffer.size()
```

Use `initialize_buffers(["NVDA"], ["5m", "33m"])` for a smaller selection, or
`CandleBuffer()` for a standalone buffer that binds to the first candle's pair.
`extend` commits the batch only if every item is accepted. `copy` supplies an
independent candidate buffer for persistence/recovery processing.

Identical candles still in the buffer are ignored on replay. Conflicting revisions,
mixed ticker/timeframe inputs, overlapping intervals, and out-of-order candles
raise an error rather than silently corrupting SMA history. Old candles already
evicted cannot be verified and also raise an error. The checkpoint/recovery
module determines which history to load; RAM duplicate checks alone do not provide
crash recovery. The fetcher remains responsible for session and completion rules.

No Phase 3 tests or API requests were run.

## Phase 4: InfluxDB storage

`storage/influx.py` contains one `InfluxStorage` class for database operations.
It targets **InfluxDB v2 with Flux queries**, following the original specification's
URL/token/organization/bucket settings. The actual deployment version is still
unconfirmed. InfluxDB 3 would require a different query implementation.

When ready, install the dependency from `requirements.txt`, create a bucket in
your InfluxDB instance, and fill in `INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG`, and
`INFLUX_BUCKET` locally in `.env`. The token needs read and write access to that
bucket. The code does not create buckets or change retention settings.

```python
from storage.influx import InfluxStorage

with InfluxStorage() as storage:
    # Optional manual read-access check; this does not verify write permission.
    # storage.check_connection()
    # storage.save_candle(candle)
    # storage.save_candles(history)
    # storage.save_hit(hit)
    # storage.save_hits(hits)
    history = storage.load_latest_candles("NVDA", "33m", limit=999)
```

The example needs configured credentials before it can run. Importing the module
does not connect. Creating the client requires credentials but does not itself
perform a read or write. `close()` or the `with` block releases resources.

- `ohlc` stores open, high, low, close, and interval start; no volume. The point
  timestamp is the candle's completion time. Symbol, timeframe, and research
  version are tags. Prices are stored without comparison rounding.
- `sma_hits` stores SMA value, matched OHLC value, and an outfit-membership
  snapshot. Symbol, timeframe, SMA period, OHLC field, and research version form
  the tags. Its point timestamp matches the candle's completion time.
- `sma_hit.py` defines the small `SMAHit` dataclass accepted by `save_hit`. It
  validates the two-decimal match but does not calculate SMAs or detect hits.
- The research version starts at `v1` in `config.py`. Change it for changes to
  research definitions so new records do not overwrite the previous version.
  Reads select the current version.
- Identical points have stable measurement/tag/timestamp identities, allowing
  ordinary retries without adding duplicate records. This does not implement
  correction handling or ranking counters. Phase 10 adds separate durable progress records.
- Writes are synchronous, in batches of up to 500 points. If a later batch fails,
  earlier batches may already be saved. `StorageError` reports database failures;
  callers must not treat a failed write as completed processing.
- `load_latest_candles` returns up to 999 candles, oldest first, in aware Eastern
  Time. `end=checkpoint_time` includes the checkpoint candle for recovery.
  Empty successful reads return an empty list; failures raise an error. Older
  database history remains available and is not deleted by this method.

No Phase 4 tests, database checks, or writes were run. The new client dependency
is listed in `requirements.txt`; install it before using the storage module.

Reference: [InfluxDB's Python client guide](https://docs.influxdata.com/influxdb/cloud/api-guide/client-libraries/python/).

## Phase 5: history initialization

`history_loader.py` connects the fetcher, storage, and candle buffers:

1. Restore up to 999 stored candles for a ticker/timeframe through a fixed startup cutoff.
2. Retrieve newer completed candles if the stored history is stale, even if there
   are already 999 candles. Save newer data in bounded date windows.
3. If the buffer still has fewer than 999 candles, fetch only the remaining count
   before its earliest interval, or the latest 999 when no history exists.
4. Save retrieved candles before making the completed buffer available.

```python
from candle_buffer import initialize_buffers
from fetcher import MassiveFetcher
from history_loader import initialize_history
from storage.influx import InfluxStorage

# Start small when credentials are available; omit arguments for all configured pairs.
buffers = initialize_buffers(["NVDA"], ["5m", "33m"])
with InfluxStorage() as storage, MassiveFetcher() as fetcher:
    statuses = initialize_history(buffers, storage, fetcher)
```

This example performs reads and writes when run; it has not been executed.
`initialize_history` returns a status for each `(symbol, timeframe)`:

- `READY`: the requested buffer capacity is filled.
- `PARTIAL`: some candles exist; only SMA periods up to that count can be calculated.
- `EMPTY`: no history was found within the fetcher's search limit.
- `FAILED`: fetching, saving, reading, or history validation failed. Other pairs
  continue; the failed pair's previous buffer is unchanged and must not be used
  for live processing.

`load_history` handles one pair and returns its new buffer. Both functions accept
`end=...` to initialize through an earlier timestamp. Partial database writes may
remain after a failure; retrying uses the same stable candle identities.

This phase prepares **warm-up candles only**. It does not calculate historical
hits, advance a processing checkpoint, or implement crash recovery for hit
detection. Phase 10 recovery loads the buffer at the last processed checkpoint
and replay missed candles through the SMA/hit engine in order. Do not substitute
a buffer warmed to the present for that checkpoint-based replay.

The loader relies on stored history being complete up to its newest candle. It
does not infer whether gaps inside old history were missing downloads or genuine
no-trade intervals, and it does not repair provider revisions. Current fetching
is sequential per pair; downloads across different timeframes are not yet shared
by this startup loader. No new tests or live checks were run.

## Phase 6: SMA calculation

`sma.py` contains two simple functions:

- `calculate_sma(closes, period)` averages the latest `period` closing prices.
  It returns `None` if there are too few candles and rejects invalid periods.
- `calculate_smas(closes)` calculates every unique period from `config.py` once
  and returns a dictionary keyed by period. Unsupported periods remain `None`.

```python
from sma import calculate_sma, calculate_smas

# Use a populated buffer from the history loader, or a buffer updated with a
# newly completed candle. The newest candle must already be in the buffer.
buffer = buffers[("NVDA", "33m")]
closes = buffer.closes()
sma_44 = calculate_sma(closes, 44)
sma_values = calculate_smas(closes)
# sma_values[44] is the average of the latest 44 closes, or None if unavailable.
```

Prices must be ordered oldest to newest. The newest candle's close participates
in its own SMA. SMA 999 uses all 999 closes; SMA 44 uses only the latest 44.
Shared periods are calculated once even if they belong to multiple outfits.
Results are not rounded here: two-decimal comparison belongs in the hit detector.

These functions do not fetch, save, or change candles and do not require API keys.
No new tests or live checks were run.

## Phase 7: hit detection

`hit_detector.py` provides `detect_hits(candle, sma_values)`. It compares the
candle's open, high, low, and close with every available SMA using:

```python
round(ohlc_value, 2) == round(sma_value, 2)
```

It returns a list of `SMAHit` records with the candle's symbol, timeframe,
completion timestamp, SMA period/value, and matching OHLC field/value. Original
prices are preserved in the records; rounding is used only for comparison.
SMAs with `None` values are skipped. An empty list means no matches. Invalid
periods and nonfinite SMA values raise an error rather than becoming a no-hit result.

```python
from hit_detector import detect_hits
from sma import calculate_smas

# Use a buffer that already contains the completed candle being evaluated.
buffer = buffers[("NVDA", "33m")]
candle = buffer.latest()
if candle is not None:
    sma_values = calculate_smas(buffer.closes())
    hits = detect_hits(candle, sma_values)
    # Later integration can persist these with storage.save_hits(hits).
```

All matches are returned. If both high and close match SMA 44, they produce two
separate hit records. A period shared by several outfits still produces one
physical record per matching OHLC field; the existing storage layer snapshots
its outfit memberships, and the ranking module credits each outfit.

The detector is deliberately independent of fetching, storage, and counting.
Callers must pass SMAs calculated for the same candle, ticker, and timeframe.
Repeating a call returns the same matches; duplicate counting and failure-safe
processing remain the responsibility of later orchestration. No tests, API calls,
or database writes were run for this phase.

## Phase 8: scheduling

`scheduler.py` provides a sequential `Scheduler`. It checks for due work every
10 seconds (`SCHEDULER_POLL_SECONDS`) and requests a ticker/timeframe only when
a new completed interval is eligible. The fetcher's configured publication delay
still applies. The existing calendar supplies holidays, weekends, DST, early
closes, and shortened final candles.

For each due pair, the scheduler fetches all eligible candles since its retrieval
cursor and processes them oldest first:

1. Prepare a copy of the buffer containing the new candle.
2. Calculate unique SMAs and detect every matching OHLC field.
3. Save the candle and its hit records, waiting for both writes to succeed.
4. Credit the saved hits to outfit rankings and replace the active buffer with the prepared copy.

Fetch or storage errors leave the retrieval cursor unchanged and schedule a retry
after 60 seconds (`SCHEDULER_RETRY_SECONDS`). Other pairs continue. Candles already
committed to RAM are skipped on retry. Long catch-up ranges are handled in windows
of at most seven calendar days per pair per pass. Pending catch-up and retries
may run after market close; no out-of-session candles are generated.

```python
from candle_buffer import initialize_buffers
from fetcher import MassiveFetcher
from history_loader import initialize_history
from scheduler import Scheduler
from storage.influx import InfluxStorage

buffers = initialize_buffers(["NVDA"], ["5m", "33m"])
with InfluxStorage() as storage, MassiveFetcher() as fetcher:
    start = fetcher.available_until()
    statuses = initialize_history(buffers, storage, fetcher, end=start)
    scheduler = Scheduler(buffers, statuses, storage, fetcher, start=start)
    scheduler.run_forever()  # Runs until Ctrl+C or scheduler.stop().
```

This is a **first-start example**, not a crash-recovery entry point. It has not
been run. It requires working Massive and InfluxDB credentials and performs writes.
`run_once()` performs one pass and returns the count of newly processed candles.
`stop()` requests shutdown between requests/candles. The surrounding `with` blocks
close the clients. No scheduler loop starts merely by importing the module.

Pairs marked FAILED or without a startup status are excluded. READY and PARTIAL
pairs start after the newest loaded candle. EMPTY pairs begin with whole intervals
starting at or after the supplied startup time; they accumulate history normally.

Successful empty source intervals advance a separate retrieval cursor without
fabricating candles or repeatedly fetching the same no-trade interval. This uses
Phase 2's assumption that a successful provider response is complete through the
configured cutoff. Late revisions or late-arriving bars after a successful empty
response are not automatically reconciled yet.

The scheduler persists OHLC, hits, and durable progress before updating rankings
and active RAM. Phase 10's `main.py` and `recovery.py` restore the corresponding
buffer and replay later candles. Do not call the Phase 5 warm-up routine through
the present on restart; doing so would skip missed hit detection. Stable Influx
point identities allow retries. Downloads are sequential per due pair;
cross-timeframe sharing is available in the fetcher but not wired into this loop.

No tests, live collection, or database checks were run.

## Phase 9: outfit rankings

`ranking.py` provides `OutfitRankings`, a dictionary-backed counter keyed by
`(outfit, symbol, timeframe)`. Each result includes the hit count and latest hit
timestamp. One physical hit credits every outfit containing its SMA period.
Separate OHLC matches count separately: high and close matching the same SMA
contribute two hits to each associated outfit.

`top()` returns the highest counts across outfit/ticker/timeframe combinations.
Optional filters restrict the results to one ticker, one timeframe, or both.
Ties sort by newest hit, then alphabetically for stable output. Outfits with no
hits do not appear. These are raw counts, not normalized hit rates, and are not
combined across different tickers/timeframes.

```python
from ranking import OutfitRankings

# Inside an already-open InfluxStorage context, before starting live processing:
rankings = OutfitRankings()
rankings.restore(storage.load_hit_summaries())

for row in rankings.top(10, symbol="NVDA", timeframe="33m"):
    print(row.symbol, row.timeframe, row.outfit, row.hit_count, row.last_hit_timestamp)

# Pass rankings=rankings to Scheduler(...) to continue from restored counts.
# After a scheduler pass, scheduler.rankings.top() returns updated results.
```

The scheduler uses the supplied rankings object or creates an empty one, then
calls `add_hits` only after the candle and hit writes succeed. To include prior
history, explicitly restore and pass the object as shown above; `main.py` now
handles this automatically.

`load_hit_summaries` queries the active research version's retained hit history.
It counts only the saved outfit-membership field, once per physical hit, and
returns counts and latest timestamps instead of downloading every hit. Restoration
uses the memberships saved with each hit. Repeated restoration replaces RAM
counts rather than adding the same history again. Retention or manual deletion
of hit records changes what a later rebuild can count.

For live updates, the ranking object remembers the latest counted timestamp for
each ticker/timeframe/SMA/OHLC-field series. Repeated or older events in that
series are ignored, preventing replay from increasing its count. Supply new hits
in chronological order, as the scheduler does. If older missing hits are newly
backfilled, or stored hits are corrected/deleted, rebuild from InfluxDB afterward;
the incremental counter cannot identify those changes on its own. The normal
Phase 10 restart path restores stored totals and replays candles chronologically.

No tests, live queries, or writes were run.

## Phase 10: run the application

`main.py` connects configuration, logging, clients, startup/recovery, rankings,
and the scheduler. `recovery.py` owns the first-start versus restart decision.
The computation and query code remain in their existing modules.

After installing dependencies and setting working credentials in `.env`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Begin with a small selection once live validation is authorized.
.\.venv\Scripts\python.exe main.py --tickers SPY --timeframes 5m 33m

# Default: every configured ticker and timeframe.
.\.venv\Scripts\python.exe main.py

# Initialize and run one bounded processing pass, then exit.
.\.venv\Scripts\python.exe main.py --tickers SPY --timeframes 5m --once
```

With the project's environment activated, `python main.py` is equivalent.
These commands perform real API calls and InfluxDB writes; they were **not run**.
`--once` is not a dry run and does not promise that a long backlog is exhausted.
Only run one application process against a given research version at a time.

### First startup

1. Validate settings and credentials, then check InfluxDB bucket read access.
2. Load current-version processing checkpoints and stored hit summaries.
3. For a new pair, warm up history through the last eligible interval boundary.
4. Persist that boundary as its baseline before starting live processing. Warm-up
   candles do not generate historical hit counts.
5. Restore rankings and start the scheduler. Log the top outfits every five minutes
   (`RANKING_REPORT_SECONDS`) and when the loop finishes. Ctrl+C closes the clients.

### Restart and replay

The `processing_state` measurement stores symbol, timeframe, and research-version
tags, with progress time as the point timestamp. Fields record `buffer_count` and
`last_candle_time`. The progress time may be later than the last candle when an
interval had no qualifying trades.

For a pair with a checkpoint, recovery loads only the recorded number of candles
ending at that progress time and verifies the count and latest candle timestamp.
It does not fill the buffer with today's latest history. Preserving a partial
buffer's original size also preserves which SMA periods were ready at that point.

The scheduler retrieves subsequent completed candles in order, with the same
processing path used for live data:

```text
Candidate buffer -> SMA values -> hits
    -> save OHLC -> save hits -> save checkpoint
    -> update rankings and active buffer
```

Checkpoint writes happen even when a candle has zero hits. Successfully covered
empty intervals also advance durable progress without creating synthetic candles.
If a candle/hit/checkpoint write fails, the active candidate is not committed and
that pair retries. Earlier successful candle checkpoints remain valid. A write
that succeeded on the server but timed out locally can be retried using the same
point identity. After a full process crash, saved progress drives restoration.
This is ordered replay, not a multi-measurement database transaction.

Rankings are rebuilt from persisted hits before scheduling. Already-saved events
are not counted again during chronological replay. Partially written hits beyond
a checkpoint may appear in restored totals before their candle is retried; replay
completes those writes. Historical corrections/deletions still require a ranking
rebuild and explicit data repair.

### Limits before production use

- This implementation has not been run end-to-end, and recovery behavior has not
  been tested. Massive returned HTTP 401 in the earlier live check; InfluxDB
  credentials and the v2/Flux deployment still need confirmation.
- Keep checkpoint history and the OHLC needed to reconstruct its buffer. A missing
  count/latest timestamp prevents that pair from resuming; it is not silently
  replaced with newer history. Recovery assumes older OHLC has not been edited
  or removed. Provider corrections, split-adjustment reconciliation, and legacy
  data migration require an explicit repair workflow.
- Existing hits without a checkpoint cause that pair to be marked FAILED rather
  than establishing a baseline that could skip unprocessed data. Existing OHLC
  without hits can be used for a first-start warm-up.
- A startup-failed pair is excluded for that run; fix the issue and restart to
  retry initialization. Successfully initialized pairs continue independently.
- Successful provider responses are still assumed complete through the configured
  availability cutoff. Late data after an empty successful response is not
  automatically repaired.
- Full-universe request throughput, data-plan limits, retention, and memory use
  remain unmeasured. Fetching is sequential per pair; cross-timeframe source
  sharing is not yet wired into startup or the scheduler.

No tests, dependency installation, live connections, or collection were run for
Phase 10. See `SMA_PROJECT_UPDATED_SPEC.md` for the updated handoff.

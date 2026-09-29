# Candle history preload

This separate utility fetches up to **999 completed candles for every selected
ticker/timeframe** from Massive and saves them in the application's InfluxDB
`ohlc` measurement. It reuses the parent project's `config.py`, `.env`, fetcher,
calendar, Candle model, and storage client. Keep this folder inside Research.

It performs one finite preload run; it does not start the scheduler, calculate
SMAs, save hits, or establish processing checkpoints.

## Run from the Research folder

After dependencies are installed and credentials are configured:

```powershell
# Optional small selection.
.\.venv\Scripts\python.exe preload\fetch_history.py --tickers SPY --timeframes 5m 33m

# All tickers and all 59 timeframes from the shared configuration.
.\.venv\Scripts\python.exe preload\fetch_history.py

# Start the main application afterward.
.\.venv\Scripts\python.exe main.py
```

The existing requirements include everything this utility needs. It requires a
Massive key and InfluxDB v2/Flux credentials in Research's `.env`. It does not need
a second credential file. None of these commands have been run.

## How the preload works

- Fixes one completion cutoff at startup, including the configured provider delay.
- Processes one ticker at a time and searches backward in small date windows.
- Downloads Massive one-minute data once per window and shares it across all
  still-needed timeframes. The existing fetcher constructs the agreed 09:30-anchored
  regular-session candles, including shortened final candles.
- Keeps at most 999 target candles per unfinished timeframe in RAM. Once a pair
  reaches 999, validates it through a CandleBuffer and saves it to InfluxDB.
- Preserves the existing schema, research version, and completion timestamps.
  Volume is ignored. Existing unrelated historical candles are not deleted.
- Logs each saved pair and its readiness. If the search limit is reached, saves
  available partial history and reports the shortfall. No candles are fabricated.

The lookback defaults to `HISTORY_MAX_LOOKBACK_DAYS` (3,650 calendar days). Set
`--lookback-days` to suit your subscription. Provider permission errors are failures,
not evidence that the symbol has no older history. Longer timeframes may need
multiple years of source data to reach 999 candles.

## InfluxDB versus RAM

The preload holds working data in RAM while it runs, then releases that memory
when it exits. A separate Python process cannot inherit those buffers. On its
first start, `main.py` restores the saved candles from InfluxDB into its own RAM
buffers, fetching newer or missing data as needed. If time passes between preload
and startup, newer completed candles will still need fetching.

Pairs with existing processing checkpoints are skipped. `main.py` must restore
those pairs at their saved checkpoints and replay missed candles; replacing their
history here could change recovery calculations. Stop the main collector while
running the preload. This is intended to prepare untracked pairs before collection.

Rerunning the utility fetches history again for untracked pairs and writes the same
stable candle identities. It is not a download-resume system. A ticker failure or
Ctrl+C preserves previously acknowledged writes, but unfinished in-memory history
will need to be fetched again. Progress messages identify what was actually saved.

Exit code 0 means all processed pairs reached 999 (or were already tracked and
skipped); 1 means partial/empty results or an error; 130 means Ctrl+C.

No tests, API requests, database writes, or live validation were run while creating
this utility. The project's existing provider/authentication and InfluxDB-version
validation limitations still apply.

# File purpose: Saves OHLC candles and SMA hits in InfluxDB v2 and restores recent candles.

import json
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from itertools import islice

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.rest import ApiException
from urllib3.exceptions import HTTPError

from candle import Candle
from config import (
    MAX_CANDLES, NY_TIMEZONE, RESEARCH_VERSION, SMA_TO_OUTFITS,
    load_environment, require_environment,
)
from sma_hit import SMAHit
from timeframes import TIMEFRAMES


class StorageError(RuntimeError):
    """Database operation failed; callers must not mark its data as processed."""


class InfluxStorage:
    # Load settings and create a v2 client; do not make a network request yet.
    def __init__(self):
        load_environment()
        settings = require_environment("INFLUX_URL", "INFLUX_TOKEN", "INFLUX_ORG", "INFLUX_BUCKET")
        self._bucket = settings["INFLUX_BUCKET"]
        self._org = settings["INFLUX_ORG"]
        self._client = InfluxDBClient(
            url=settings["INFLUX_URL"], token=settings["INFLUX_TOKEN"],
            org=self._org, timeout=30_000,
        )
        # Synchronous writes return only after the server acknowledges the batch.
        self._writer = self._client.write_api(write_options=SYNCHRONOUS)
        self._reader = self._client.query_api()

    # Allow the storage connection to be used inside a Python with block.
    def __enter__(self) -> "InfluxStorage":
        return self

    # Close resources when the with block ends, including when processing fails.
    def __exit__(self, *_):
        self.close()

    # Close the writer and client when the application shuts down.
    def close(self) -> None:
        try:
            self._writer.close()
        finally:
            self._client.close()

    # Execute a Flux read and report failures without including credentials or response bodies.
    def _query(self, query: str, params: dict):
        try:
            return self._reader.query(query=query, org=self._org, params=params)
        except (ApiException, HTTPError, OSError):
            raise StorageError("InfluxDB read failed; check the connection, bucket, and read permission") from None

    # Check access to the configured bucket without writing any data.
    def check_connection(self) -> None:
        self._query(
            'from(bucket: params.bucket) |> range(start: -1m) |> limit(n: 1)',
            {"bucket": self._bucket},
        )

    # Write at most 500 points per request, waiting for acknowledgment after each batch.
    def _write_points(self, points: Iterable[Point]) -> None:
        iterator = iter(points)
        while batch := list(islice(iterator, 500)):
            try:
                self._writer.write(bucket=self._bucket, org=self._org, record=batch)
            except (ApiException, HTTPError, OSError):
                raise StorageError("InfluxDB write failed; do not advance the processing checkpoint") from None

    # Convert a candle into an OHLC point labeled with the candle's completion time.
    def _candle_point(self, candle: Candle) -> Point:
        return (
            Point("ohlc")
            .tag("symbol", candle.symbol)
            .tag("timeframe", candle.timeframe)
            .tag("research_version", RESEARCH_VERSION)
            .field("open", float(candle.open))
            .field("high", float(candle.high))
            .field("low", float(candle.low))
            .field("close", float(candle.close))
            .field("start_time", candle.start_time.astimezone(timezone.utc).isoformat())
            .time(candle.timestamp.astimezone(timezone.utc), WritePrecision.NS)
        )

    # Save one candle using the same write path as a historical batch.
    def save_candle(self, candle: Candle) -> None:
        self.save_candles([candle])

    # Save candle history in bounded batches without loading the entire iterable into memory.
    def save_candles(self, candles: Iterable[Candle]) -> None:
        self._write_points(self._candle_point(candle) for candle in candles)

    # Convert a match into a point with a stable identity and its current outfit memberships.
    def _hit_point(self, hit: SMAHit) -> Point:
        return (
            Point("sma_hits")
            .tag("symbol", hit.symbol)
            .tag("timeframe", hit.timeframe)
            .tag("research_version", RESEARCH_VERSION)
            .tag("sma_period", str(hit.sma_period))
            .tag("ohlc_field", hit.ohlc_field)
            .field("sma_value", float(hit.sma_value))
            .field("ohlc_value", float(hit.ohlc_value))
            .field("outfits", json.dumps(SMA_TO_OUTFITS[hit.sma_period]))
            .time(hit.timestamp.astimezone(timezone.utc), WritePrecision.NS)
        )

    # Save one SMA hit using its matching candle's timestamp.
    def save_hit(self, hit: SMAHit) -> None:
        self.save_hits([hit])

    # Save all hits from a candle or historical batch using acknowledged writes.
    def save_hits(self, hits: Iterable[SMAHit]) -> None:
        self._write_points(self._hit_point(hit) for hit in hits)

    # Persist how far a pair is fully processed and the exact buffer size needed on restart.
    def save_checkpoint(self, symbol: str, timeframe: str, timestamp: datetime,
                        buffer_count: int, last_candle_time: datetime | None) -> None:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Checkpoint timestamp must be timezone-aware")
        if type(buffer_count) is not int or not 0 <= buffer_count <= MAX_CANDLES:
            raise ValueError("Invalid checkpoint buffer count")
        if (buffer_count == 0) != (last_candle_time is None):
            raise ValueError("Checkpoint count and last candle must agree")
        if last_candle_time is not None:
            if last_candle_time.tzinfo is None or last_candle_time.utcoffset() is None:
                raise ValueError("Last candle timestamp must be timezone-aware")
            if last_candle_time > timestamp:
                raise ValueError("Checkpoint cannot precede its last candle")
        point = (
            Point("processing_state")
            .tag("symbol", symbol).tag("timeframe", timeframe)
            .tag("research_version", RESEARCH_VERSION)
            .field("buffer_count", buffer_count)
            .field("last_candle_time", last_candle_time.astimezone(timezone.utc).isoformat()
                   if last_candle_time is not None else "")
            .time(timestamp.astimezone(timezone.utc), WritePrecision.NS)
        )
        self._write_points([point])

    # Load the newest durable processing checkpoint for each pair in the current research version.
    def load_checkpoints(self) -> dict[tuple[str, str], dict]:
        query = '''
from(bucket: params.bucket)
    |> range(start: 0)
    |> filter(fn: (r) => r._measurement == "processing_state")
    |> filter(fn: (r) => r.research_version == params.version)
    |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    |> group(columns: ["symbol", "timeframe"])
    |> sort(columns: ["_time"], desc: true)
    |> limit(n: 1)
'''
        tables = self._query(query, {"bucket": self._bucket, "version": RESEARCH_VERSION})
        checkpoints = {}
        try:
            for table in tables:
                for record in table.records:
                    values = record.values
                    count = values["buffer_count"]
                    timestamp = record.get_time()
                    last = datetime.fromisoformat(values["last_candle_time"]) if values["last_candle_time"] else None
                    if type(count) is not int or not 0 <= count <= MAX_CANDLES:
                        raise ValueError("Invalid checkpoint count")
                    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                        raise ValueError("Invalid checkpoint time")
                    if (count == 0) != (last is None):
                        raise ValueError("Incomplete checkpoint")
                    if last is not None and (last.tzinfo is None or last.utcoffset() is None or last > timestamp):
                        raise ValueError("Invalid checkpoint last candle")
                    checkpoints[(values["symbol"], values["timeframe"])] = {
                        "timestamp": timestamp.astimezone(NY_TIMEZONE),
                        "buffer_count": count,
                        "last_candle_time": last.astimezone(NY_TIMEZONE) if last else None,
                    }
        except (KeyError, TypeError, ValueError, AttributeError):
            raise StorageError("Stored processing checkpoints are invalid; startup stopped") from None
        return checkpoints

    # Summarize hits for all history or an inclusive timestamp window, counting each physical hit once.
    def load_hit_summaries(self, *, start: datetime | None = None,
                           end: datetime | None = None) -> list[dict]:
        first = start if start is not None else datetime(1970, 1, 1, tzinfo=timezone.utc)
        last = end if end is not None else datetime.now(timezone.utc)
        for timestamp in (first, last):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Hit query bounds must be timezone-aware")
        if first > last:
            raise ValueError("Hit query start must not be after end")
        # Flux excludes stop, so add one microsecond to include a candle at the close.
        stop = last.astimezone(timezone.utc) + timedelta(microseconds=1)
        # Only the outfits field is counted; counting every field would multiply
        # each physical hit. Saved memberships preserve the original attribution.
        query = '''
from(bucket: params.bucket)
    |> range(start: time(v: params.start), stop: time(v: params.stop))
    |> filter(fn: (r) => r._measurement == "sma_hits" and r._field == "outfits")
    |> filter(fn: (r) => r.research_version == params.version)
    |> rename(columns: {_value: "outfits"})
    |> group(columns: ["symbol", "timeframe", "sma_period", "ohlc_field", "outfits"])
    |> reduce(
        identity: {hit_count: 0, last_hit_timestamp: time(v: 0)},
        fn: (r, accumulator) => ({
            hit_count: accumulator.hit_count + 1,
            last_hit_timestamp: if r._time > accumulator.last_hit_timestamp
                then r._time else accumulator.last_hit_timestamp
        })
    )
'''
        tables = self._query(query, {
            "bucket": self._bucket, "version": RESEARCH_VERSION,
            "start": first.astimezone(timezone.utc).isoformat(), "stop": stop.isoformat(),
        })
        summaries = []
        try:
            for table in tables:
                for record in table.records:
                    values = record.values
                    outfits = json.loads(values["outfits"])
                    if (not isinstance(outfits, list) or not outfits
                            or any(not isinstance(name, str) or not name for name in outfits)
                            or len(set(outfits)) != len(outfits)):
                        raise ValueError("Invalid saved outfit memberships")
                    timestamp = values["last_hit_timestamp"]
                    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                        raise ValueError("Invalid saved hit timestamp")
                    summaries.append({
                        "symbol": values["symbol"], "timeframe": values["timeframe"],
                        "sma_period": int(values["sma_period"]), "ohlc_field": values["ohlc_field"],
                        "outfits": outfits, "hit_count": int(values["hit_count"]),
                        "last_hit_timestamp": timestamp.astimezone(NY_TIMEZONE),
                    })
        except (KeyError, TypeError, ValueError, AttributeError):
            raise StorageError("Stored hit summaries are invalid; rankings were not restored") from None
        return summaries

    # Read the latest N candles, optionally ending at a recovery checkpoint, oldest first.
    def load_latest_candles(self, symbol: str, timeframe: str, limit: int = MAX_CANDLES,
                            *, end: datetime | None = None) -> list[Candle]:
        if not symbol.strip() or timeframe not in TIMEFRAMES:
            raise ValueError("Specify a symbol and supported timeframe")
        if type(limit) is not int or not 1 <= limit <= MAX_CANDLES:
            raise ValueError(f"limit must be between 1 and {MAX_CANDLES}")
        stop = datetime.now(timezone.utc)
        if end is not None:
            if end.tzinfo is None or end.utcoffset() is None:
                raise ValueError("History end must be timezone-aware")
            # Flux's stop is exclusive; include the checkpoint candle itself.
            stop = end.astimezone(timezone.utc) + timedelta(microseconds=1)
        query = '''
from(bucket: params.bucket)
    |> range(start: 0, stop: time(v: params.stop))
    |> filter(fn: (r) => r._measurement == "ohlc")
    |> filter(fn: (r) => r.symbol == params.symbol and r.timeframe == params.timeframe)
    |> filter(fn: (r) => r.research_version == params.version)
    |> filter(fn: (r) => contains(value: r._field, set: ["open", "high", "low", "close", "start_time"]))
    |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    |> group(columns: [])
    |> sort(columns: ["_time"], desc: true)
    |> limit(n: params.limit)
    |> sort(columns: ["_time"])
'''
        tables = self._query(query, {
            "bucket": self._bucket, "symbol": symbol, "timeframe": timeframe,
            "version": RESEARCH_VERSION, "limit": limit, "stop": stop.isoformat(),
        })
        candles = []
        try:
            for table in tables:
                for record in table.records:
                    values = record.values
                    candles.append(Candle(
                        symbol=symbol, timeframe=timeframe,
                        start_time=datetime.fromisoformat(values["start_time"]),
                        timestamp=record.get_time(),
                        open=float(values["open"]), high=float(values["high"]),
                        low=float(values["low"]), close=float(values["close"]),
                    ))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise StorageError("Stored OHLC data is incomplete or invalid; history was not restored") from None
        return sorted(candles, key=lambda candle: candle.timestamp)

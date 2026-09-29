# File purpose: Count SMA hits per outfit/ticker/timeframe and return the highest-ranked results.

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import logging

from config import SMA_TO_OUTFITS, TOP_N_OUTFITS
from sma_hit import SMAHit


@dataclass(frozen=True)
class OutfitRank:
    outfit: str
    symbol: str
    timeframe: str
    hit_count: int
    last_hit_timestamp: datetime


class OutfitRankings:
    # Create counts keyed by outfit/ticker/timeframe and replay guards per physical hit series.
    def __init__(self):
        self._ranks: dict[tuple[str, str, str], OutfitRank] = {}
        self._last_counted: dict[tuple[str, str, int, str], datetime] = {}

    # Credit one outfit and retain its most recent hit time.
    def _credit(self, outfit: str, symbol: str, timeframe: str, count: int, timestamp: datetime) -> None:
        key = (outfit, symbol, timeframe)
        previous = self._ranks.get(key)
        self._ranks[key] = OutfitRank(
            outfit, symbol, timeframe,
            count + (previous.hit_count if previous else 0),
            max(timestamp, previous.last_hit_timestamp) if previous else timestamp,
        )

    # Count newly saved hits in chronological order, crediting every outfit containing each SMA.
    def add_hits(self, hits: Iterable[SMAHit]) -> None:
        for hit in hits:
            series = (hit.symbol, hit.timeframe, hit.sma_period, hit.ohlc_field)
            previous = self._last_counted.get(series)
            # A series can have only one event at a candle timestamp. Remembering
            # its latest time avoids keeping an ever-growing set of event IDs.
            if previous is not None and hit.timestamp <= previous:
                continue
            for outfit in SMA_TO_OUTFITS[hit.sma_period]:
                self._credit(outfit, hit.symbol, hit.timeframe, 1, hit.timestamp)
            self._last_counted[series] = hit.timestamp

    # Replace RAM counts with database summaries, using the outfit memberships saved with the hits.
    def restore(self, summaries: Iterable[dict]) -> None:
        restored = OutfitRankings()
        for summary in summaries:
            for outfit in summary["outfits"]:
                restored._credit(
                    outfit, summary["symbol"], summary["timeframe"],
                    summary["hit_count"], summary["last_hit_timestamp"],
                )
            series = (summary["symbol"], summary["timeframe"], summary["sma_period"], summary["ohlc_field"])
            timestamp = summary["last_hit_timestamp"]
            previous = restored._last_counted.get(series)
            restored._last_counted[series] = max(previous, timestamp) if previous else timestamp
        self._ranks = restored._ranks
        self._last_counted = restored._last_counted

    # Return the highest counts, optionally restricted to one ticker and/or timeframe.
    def top(self, limit: int = TOP_N_OUTFITS, *, symbol: str | None = None,
            timeframe: str | None = None) -> list[OutfitRank]:
        if type(limit) is not int or limit < 1:
            raise ValueError("Ranking limit must be a positive integer")
        rows = [row for row in self._ranks.values()
                if (symbol is None or row.symbol == symbol)
                and (timeframe is None or row.timeframe == timeframe)]
        return sorted(rows, key=lambda row: (
            -row.hit_count, -row.last_hit_timestamp.timestamp(),
            row.outfit, row.symbol, row.timeframe,
        ))[:limit]

    # Print the current highest-ranked outfit/ticker/timeframe combinations to the application log.
    def log_top(self) -> None:
        logger = logging.getLogger(__name__)
        rows = self.top()
        if not rows:
            logger.info("No SMA hits recorded for the active research version")
        for position, row in enumerate(rows, start=1):
            logger.info("Rank %d | %s | %s | %s | %d hits | last %s",
                        position, row.symbol, row.timeframe, row.outfit,
                        row.hit_count, row.last_hit_timestamp.isoformat())

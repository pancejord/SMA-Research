# File purpose: Keeps up to 999 candles per ticker/timeframe in RAM for later SMA calculations.
"""Bounded, chronological RAM storage; no fetching or database access."""

from collections import deque
from collections.abc import Iterable

from candle import Candle
from config import MAX_CANDLES, TICKERS
from timeframes import TIMEFRAMES


class CandleBuffer:
    """One ticker/timeframe's most recent completed candles, oldest first.

    A standalone buffer binds to its first candle. Factory-created buffers are
    bound immediately. Identical retained candles are safe to replay; revisions
    and out-of-order inserts require explicit history reconstruction instead.
    """

    # Create an empty buffer with a size limit and optional ticker/timeframe assignment.
    def __init__(self, max_size: int = MAX_CANDLES, *,
                 symbol: str | None = None, timeframe: str | None = None):
        if type(max_size) is not int or not 1 <= max_size <= MAX_CANDLES:
            raise ValueError(f"max_size must be an integer between 1 and {MAX_CANDLES}")
        if (symbol is None) != (timeframe is None):
            raise ValueError("Specify both symbol and timeframe, or neither")
        if symbol is not None and (not isinstance(symbol, str) or not symbol.strip()):
            raise ValueError("Symbol must be a nonempty string")
        if timeframe is not None and timeframe not in TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        self._candles: deque[Candle] = deque(maxlen=max_size)
        self._key = (symbol, timeframe) if symbol is not None else None

    # Return the maximum number of candles this buffer can hold.
    @property
    def max_size(self) -> int:
        return self._candles.maxlen

    # Return a read-only snapshot of the stored candles, ordered oldest to newest.
    @property
    def candles(self) -> tuple[Candle, ...]:
        """Read-only snapshot so callers cannot bypass ordering/duplicate checks."""
        return tuple(self._candles)

    # Add one new candle, skip an identical replay, and reject conflicting or incorrectly ordered data.
    def add(self, candle: Candle) -> bool:
        """Append once; return True if added, False for an identical replay.

        Raise ValueError on mixed pairs, revised data, overlapping intervals, or
        an old candle that is no longer retained. No state changes on rejection.
        """
        if not isinstance(candle, Candle):
            raise TypeError("Expected a Candle")
        key = (candle.symbol, candle.timeframe)
        if self._key is not None and key != self._key:
            raise ValueError("Candle belongs to a different ticker/timeframe")
        latest = self.latest()
        if latest is not None:
            if candle.timestamp <= latest.timestamp:
                for existing in reversed(self._candles):
                    if existing.timestamp == candle.timestamp:
                        if existing == candle:
                            return False
                        raise ValueError("Revised candle detected; rebuild the affected history")
                raise ValueError("Out-of-order candle; restore history in chronological order")
            if candle.start_time < latest.timestamp:
                raise ValueError("Candle interval overlaps the latest retained candle")
        self._candles.append(candle)
        self._key = key
        return True

    # Add an oldest-first batch only if every candle is accepted; otherwise leave the buffer unchanged.
    def extend(self, candles: Iterable[Candle]) -> int:
        """Add an oldest-first batch atomically; return the number newly added.

        Input can be a generator. Only a bounded candidate buffer is retained.
        A rejected candle or failed iterator leaves this buffer unchanged.
        """
        candidate = self.copy()
        added = 0
        for candle in candles:
            added += candidate.add(candle)
        self._candles = candidate._candles
        self._key = candidate._key
        return added

    # Return the newest candle, or None when the buffer is empty.
    def latest(self) -> Candle | None:
        return self._candles[-1] if self._candles else None

    # Return the stored closing prices in order so SMAs can use the most recent N prices.
    def closes(self) -> list[float]:
        """Unrounded closing prices in chronological order for the SMA engine."""
        return [candle.close for candle in self._candles]

    # Return the number of candles currently stored in the buffer.
    def size(self) -> int:
        return len(self._candles)

    # Create an independent copy so later processing can prepare changes before committing them.
    def copy(self) -> "CandleBuffer":
        """Independent candidate state for later failure-safe processing."""
        candidate = CandleBuffer(self.max_size)
        candidate._key = self._key
        candidate._candles.extend(self._candles)
        return candidate


# Create an empty rolling buffer for every requested ticker/timeframe pair.
def initialize_buffers(
    tickers: Iterable[str] | None = None,
    timeframes: Iterable[str] | None = None,
) -> dict[tuple[str, str], CandleBuffer]:
    """Create empty buffers keyed by (symbol, timeframe); perform no I/O."""
    symbols = TICKERS if tickers is None else tickers
    frames = tuple(TIMEFRAMES if timeframes is None else timeframes)
    return {
        (symbol, timeframe): CandleBuffer(symbol=symbol, timeframe=timeframe)
        for symbol in symbols
        for timeframe in frames
    }

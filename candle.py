# File purpose: Defines one OHLC candle and validates its prices and Eastern Time timestamps.
"""Provider-independent model for a completed OHLC candle."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from config import NY_TIMEZONE
from timeframes import TIMEFRAMES


@dataclass(frozen=True)
class Candle:
    """Timestamp is the interval END, including shortened session-close bars.

    Datetimes must be aware and are normalized to America/New_York. Prices are
    preserved without rounding; two-decimal rounding belongs in hit detection.
    Session membership and completion must be checked by the data pipeline.
    """

    symbol: str
    timeframe: str
    start_time: datetime
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float

    # Validate the candle after creation and convert its start/end timestamps to Eastern Time.
    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("Candle symbol must not be empty")
        if self.timeframe not in TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe: {self.timeframe}")
        for name in ("start_time", "timestamp"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
            object.__setattr__(self, name, value.astimezone(NY_TIMEZONE))
        if self.timestamp <= self.start_time:
            raise ValueError("Candle timestamp must be after start_time")
        if not all(isfinite(value) for value in (self.open, self.high, self.low, self.close)):
            raise ValueError("Candle OHLC must be finite")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError("Candle OHLC values must lie within low/high")

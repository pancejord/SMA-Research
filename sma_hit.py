# File purpose: Defines one timestamped OHLC-to-SMA match for storage and later ranking.

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from config import ALL_SMA_PERIODS, NY_TIMEZONE, PRICE_DECIMALS
from timeframes import TIMEFRAMES


@dataclass(frozen=True)
class SMAHit:
    symbol: str
    timeframe: str
    timestamp: datetime
    sma_period: int
    sma_value: float
    ohlc_field: str
    ohlc_value: float

    # Check the hit's identity, timestamp, and rounded equality before it can be saved.
    def __post_init__(self) -> None:
        if not self.symbol.strip() or self.timeframe not in TIMEFRAMES:
            raise ValueError("Hit requires a symbol and supported timeframe")
        if type(self.sma_period) is not int or self.sma_period not in ALL_SMA_PERIODS:
            raise ValueError("Hit must use a configured SMA period")
        if self.ohlc_field not in ("open", "high", "low", "close"):
            raise ValueError("Hit OHLC field must be open, high, low, or close")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("Hit timestamp must be timezone-aware")
        if not isfinite(self.sma_value) or not isfinite(self.ohlc_value):
            raise ValueError("Hit prices must be finite")
        if round(self.sma_value, PRICE_DECIMALS) != round(self.ohlc_value, PRICE_DECIMALS):
            raise ValueError("Hit prices must match after two-decimal rounding")
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(NY_TIMEZONE))

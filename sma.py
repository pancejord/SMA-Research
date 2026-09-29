# File purpose: Calculate closing-price SMAs for the newest candle in a rolling buffer.

from collections.abc import Sequence

from config import ALL_SMA_PERIODS


# Average the latest N closing prices, or return None if there are not enough candles.
def calculate_sma(closes: Sequence[float], period: int) -> float | None:
    if type(period) is not int or period < 1:
        raise ValueError("SMA period must be a positive integer")
    if len(closes) < period:
        return None

    # Closing prices must be oldest first, including the newest completed candle.
    # Keep the result unrounded; the hit detector will apply two-decimal rounding.
    return sum(closes[-period:]) / period


# Calculate each unique configured SMA once and return its value keyed by period.
def calculate_smas(closes: Sequence[float]) -> dict[int, float | None]:
    return {
        period: calculate_sma(closes, period)
        for period in ALL_SMA_PERIODS
    }

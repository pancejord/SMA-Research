# File purpose: Find every OHLC-to-SMA match for a completed candle using two-decimal equality.

from math import isfinite

from candle import Candle
from config import ALL_SMA_PERIODS, PRICE_DECIMALS
from sma_hit import SMAHit


# Compare all four candle prices with each available SMA and return every matching event.
def detect_hits(candle: Candle, sma_values: dict[int, float | None]) -> list[SMAHit]:
    """SMA values must belong to this candle and include its closing price."""
    prices = {
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
    }
    rounded_prices = {
        field: round(price, PRICE_DECIMALS)
        for field, price in prices.items()
    }
    hits = []

    for period, sma_value in sma_values.items():
        if type(period) is not int or period not in ALL_SMA_PERIODS:
            raise ValueError("Hit detection requires configured SMA periods")
        if sma_value is None:
            continue
        if not isfinite(sma_value):
            raise ValueError("SMA values must be finite")

        rounded_sma = round(sma_value, PRICE_DECIMALS)
        for field, rounded_price in rounded_prices.items():
            if rounded_price == rounded_sma:
                # Preserve original prices and the candle's completion timestamp.
                # Shared outfit membership is handled by storage and ranking.
                hits.append(SMAHit(
                    symbol=candle.symbol,
                    timeframe=candle.timeframe,
                    timestamp=candle.timestamp,
                    sma_period=period,
                    sma_value=sma_value,
                    ohlc_field=field,
                    ohlc_value=prices[field],
                ))

    return hits

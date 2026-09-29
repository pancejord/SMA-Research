# File purpose: Defines the 59 supported timeframes: 5 through 59 minutes and 1 through 4 hours.
"""Timeframe durations; provider aggregates still require alignment validation."""

TIMEFRAMES = {}


for minute in range(5, 60):
    TIMEFRAMES[f"{minute}m"] = {
        "multiplier": minute,
        "timespan": "minute"
    }

for hour in range(1, 5):
    TIMEFRAMES[f"{hour}h"] = {
        "multiplier": hour,
        "timespan": "hour"
    }

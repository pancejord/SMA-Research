# File purpose: Checks configuration and imports without contacting Massive or InfluxDB.
"""Offline Phase 1 validation: python check_foundation.py."""

from config import ALL_SMA_PERIODS, OUTFITS, TICKERS, load_environment, validate_config
from candle import Candle  # Validate the model's imports as part of this check.
from timeframes import TIMEFRAMES


# Run the offline configuration check and print the configured universe sizes.
def main() -> None:
    load_environment()
    validate_config()
    print(
        f"Foundation OK: {len(TICKERS)} tickers, {len(TIMEFRAMES)} timeframes, "
        f"{len(OUTFITS)} outfits, {len(ALL_SMA_PERIODS)} unique SMA periods "
        f"(maximum {max(ALL_SMA_PERIODS)})."
    )
    print("Offline check only; API credentials and database connectivity are not verified.")


if __name__ == "__main__":
    main()

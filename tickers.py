# File purpose: Makes the ticker list from config.py available without maintaining a second list.
"""Compatibility export; edit the ticker universe only in config.py."""

from config import TICKERS

__all__ = ["TICKERS"]

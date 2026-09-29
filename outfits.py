# File purpose: Makes the outfits and derived SMA lookups from config.py available to other modules.
"""Compatibility exports; edit SMA outfits only in config.py."""

from config import ALL_SMA_PERIODS, OUTFITS, SMA_TO_OUTFITS

__all__ = ["OUTFITS", "ALL_SMA_PERIODS", "SMA_TO_OUTFITS"]

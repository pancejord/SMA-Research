# File purpose: Stores tickers, SMA outfits, application settings, and helpers for loading credentials.
"""Non-secret settings and the authoritative ticker/outfit configuration."""

import os
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent
MAX_CANDLES = 999
PRICE_DECIMALS = 2
MARKET_TIMEZONE = "America/New_York"
NY_TIMEZONE = ZoneInfo(MARKET_TIMEZONE)
# Normal-session defaults. The scheduler must use a calendar for actual sessions.
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
USE_EXTENDED_HOURS = False
KEEP_SHORT_FINAL_CANDLE = True
SAVE_OHLC = True
SAVE_SMA_HITS = True
SAVE_ALL_SMA_VALUES = False
TOP_N_OUTFITS = 10
LOG_LEVEL = "INFO"
IGNORE_DUPLICATE_CANDLES = True
MASSIVE_BASE_URL = "https://api.massive.com"
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_MAX_ATTEMPTS = 3
# Increase for a delayed data plan. This is a publication buffer, not a guarantee
# against later provider corrections; recovery/reconciliation is a later phase.
DATA_DELAY_SECONDS = 60
HISTORY_MAX_LOOKBACK_DAYS = 3650
# Change this when research rules change so new results do not overwrite old ones.
RESEARCH_VERSION = "v1"
SCHEDULER_POLL_SECONDS = 10
SCHEDULER_RETRY_SECONDS = 60
RANKING_REPORT_SECONDS = 300


# Load credentials from the project .env file without replacing existing environment values.
def load_environment(env_path: Path | str | None = None) -> bool:
    """Load project .env without replacing existing process environment values."""
    path = PROJECT_DIR / ".env" if env_path is None else Path(env_path)
    return load_dotenv(dotenv_path=path, override=False)


# Read required environment variables and report missing names without exposing credentials.
def require_environment(*names: str) -> dict[str, str]:
    """Return requested credentials, reporting missing names but never values.

    Call load_environment() first. Each integration requests only what it needs;
    importing configuration requires neither credentials nor network access.
    """
    values = {name: os.getenv(name, "") for name in names}
    missing = [name for name, value in values.items() if not value.strip()]
    if missing:
        raise ValueError("Missing required environment variables: " + ", ".join(missing))
    return values


TICKERS = [
    # Major ETFs / Index proxies
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "VOO",
    "IVV",
    "VTI",
    "IXIC",
    "SPX",

    # S&P leveraged/inverse
    "SSO",
    "UPRO",
    "SH",
    "SDS",
    "SPXU",
    "SPXL",
    "SPXS",

    # Nasdaq leveraged/inverse
    "QLD",
    "TQQQ",
    "PSQ",
    "QID",
    "SQQQ",

    # Dow / Russell
    "DDM",
    "UDOW",
    "DOG",
    "DXD",
    "SDOW",
    "UWM",
    "RWM",
    "TWM",
    "SRTY",
    "TNA",
    "TZA",
    "HIBL",
    "HIBS",
    "WEBS",

    # Mag 7
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOG",
    "GOOGL",
    "META",
    "TSLA",

    # NVIDIA leveraged
    "NVDX",
    "NVDQ",
    "NVDU",
    "NVDD",
    "NVDB",

    # Tesla leveraged
    "TSLL",
    "TSLS",
    "TSLT",
    "TSLZ",
    "TSLI",

    # Apple leveraged
    "AAPU",
    "AAPD",
    "AAPX",

    # Microsoft leveraged
    "MSFU",
    "MSFD",
    "MSFX",
    "MSTU",

    # Amazon leveraged
    "AMZU",
    "AMZD",

    # Google leveraged
    "GGLL",
    "GGLS",
    "GOOX",

    # Meta leveraged
    "METU",
    "METD",

    # Semiconductors
    "AMD",
    "AVGO",
    "MU",
    "INTC",
    "ARM",
    "QCOM",
    "TSM",
    "MRVL",
    "ADI",
    "SMH",
    "SOXX",
    "USD",
    "SSG",
    "SOXL",
    "SOXS",
    "MUU",
    "MUD",
    "AMUU",
    "AMDD",

    # VIX / volatility
    "VIX",
    "VIXY",
    "VIXM",
    "UVXY",
    "SVXY",
    "UVIX",
    "SVIX",
    "VXX",
    "VXZ",

    # Energy / oil
    "XOM",
    "CVX",
    "COP",
    "OXY",
    "EOG",
    "SLB",
    "HAL",
    "MPC",
    "VLO",
    "PSX",
    "DVN",
    "XLE",
    "XOP",
    "OIH",
    "DIG",
    "DUG",
    "GUSH",
    "DRIP",
    "USO",
    "UCO",
    "SCO",
    "UNG",
    "BOIL",
    "KOLD",

    # Financials
    "JPM",
    "BAC",
    "WFC",
    "C",
    "GS",
    "MS",
    "SCHW",
    "AXP",
    "V",
    "MA",
    "BLK",
    "BX",
    "KKR",
    "APO",
    "COF",
    "USB",
    "PNC",
    "TFC",
    "HOOD",
    "COIN",
    "XLF",
    "KRE",
    "KBE",
    "UYG",
    "SKF",
    "SEF",
    "FAS",
    "FAZ",

    # High beta / growth
    "PLTR",
    "PTIR",
    "PLTZ",
    "RBLX",
    "SNOW",
    "CRWD",
    "NET",
    "SHOP",
    "UBER",
    "ABNB",
    "SMCI",
    "DELL",
    "APP",
    "ASTS",
    "RKLB",
]


OUTFITS = {
    "SPX": [10, 50, 200],
    "NAS": [20, 100, 250],
    "DJI": [30, 60, 90, 300, 600, 900],
    "AN1": [33, 66, 99, 333, 666, 999],
    "AN2": [11, 44, 88, 111, 444, 888],
    "AN3": [22, 55, 77, 222, 555, 777],
    "AN4": [22, 55, 77, 220, 550, 770],
    "Waring": [19, 37, 73, 143, 279, 548],
    "BETA": [21, 42, 83, 116, 332, 664],
    "BASE2_NVDA": [16, 32, 64, 128, 256, 512],
    "TSLA": [27, 53, 105, 210, 420, 840],
    "Time365": [23, 46, 91, 183, 365, 730],
    "Time366": [23, 46, 92, 183, 366, 732],
    "Time144": [18, 36, 72, 144, 288, 576],
    "ResourceMissing": [25, 51, 101, 202, 404, 808],
    "US_President_45": [29, 57, 114, 227, 455, 911],
    "US_President_46": [23, 46, 92, 184, 368, 736],
    "US_President_47": [24, 47, 94, 188, 376, 752],
    "US_Speaker": [28, 56, 112, 224, 448, 896],
    "WTC": [28, 57, 114, 228, 456, 911],
    "Russia2000": [16, 31, 63, 125, 250, 500],
    "ChinaChair": [28, 56, 112, 224, 448, 976],
    "France": [25, 50, 100, 200, 400, 600],
    "SVIX": [26, 52, 106, 211, 422, 844],
    "Turkiye": [24, 48, 96, 192, 384, 768],
    "Alphabet": [25, 50, 100, 200, 400, 800],
    "Regression": [27, 54, 108, 216, 432, 864],
    "Japans 225": [25, 45, 75, 225, 450, 900],
    "484": [22, 44, 121, 242, 484, 968],
    "232": [29, 58, 116, 232, 464, 898],
    "TSLQ Outfit": [39, 78, 156, 311, 622, 944],
    "Octople": [26, 51, 102, 204, 408, 816],
    "New": [28, 55, 111, 221, 442, 884],
    "New1": [31, 61, 122, 224, 446, 668],
    "Dust": [24, 47, 94, 188, 376, 752],
    "New2": [33, 66, 131, 262, 626, 919],
    "Ez": [20, 40, 80, 160, 320, 640],
}

ALL_SMA_PERIODS = sorted({
    period
    for periods in OUTFITS.values()
    for period in periods
})

SMA_TO_OUTFITS: dict[int, list[str]] = {}
for outfit_name, periods in OUTFITS.items():
    for period in sorted(set(periods)):
        SMA_TO_OUTFITS.setdefault(period, []).append(outfit_name)


# Check that ticker, outfit, and research settings are valid before integrations start.
def validate_config() -> None:
    """Reject invalid research settings before starting any data integrations."""
    if not TICKERS or any(not isinstance(symbol, str) or not symbol.strip() for symbol in TICKERS):
        raise ValueError("TICKERS must contain non-empty symbol strings")
    if len(TICKERS) != len(set(TICKERS)):
        raise ValueError("TICKERS contains duplicate symbols")
    if not OUTFITS:
        raise ValueError("At least one SMA outfit is required")
    for name, periods in OUTFITS.items():
        if not isinstance(name, str) or not name.strip() or not periods:
            raise ValueError("Each outfit must have a name and SMA periods")
        if any(type(period) is not int or period < 1 for period in periods):
            raise ValueError(f"Outfit {name} must use positive integer SMA periods")
        if len(periods) != len(set(periods)):
            raise ValueError(f"Outfit {name} contains duplicate SMA periods")
    if type(MAX_CANDLES) is not int or MAX_CANDLES < max(ALL_SMA_PERIODS):
        raise ValueError("MAX_CANDLES must support the largest configured SMA")
    if PRICE_DECIMALS != 2:
        raise ValueError("The current research rule requires two-decimal rounding")
    if USE_EXTENDED_HOURS:
        raise ValueError("The current research rule uses regular sessions only")
    if not KEEP_SHORT_FINAL_CANDLE:
        raise ValueError("The current research rule retains shortened final candles")

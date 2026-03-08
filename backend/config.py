# ── Configurable constants ────────────────────────────────────────────────────

import os
from pathlib import Path

# Default qualifying thresholds (full season)
MIN_AB: int = 100
MIN_IP: float = 20.0

# ── Cache settings ─────────────────────────────────────────────────────────────
# CACHE_DIR is anchored to this file's location so it resolves correctly
# regardless of the working directory — important when running as a Vercel
# serverless function where the CWD is not guaranteed to be backend/.
CACHE_DIR: str = str(Path(__file__).parent / "cache")

# In a Vercel serverless environment the cache files come from the deployment
# bundle (committed to git) and are always treated as fresh — skip TTL checks.
# In local development the normal 12-hour TTL applies.
CACHE_MAX_AGE_HOURS: int = 12
ON_VERCEL: bool = os.environ.get("VERCEL") == "1"

# Default season
DEFAULT_SEASON: int = 2025

# Last day of the 2025 regular season (used to anchor date-range windows)
SEASON_END: str = "2025-09-28"

# Timeframe windows keyed by game-count label.
# Implemented as calendar-day ranges anchored to SEASON_END because BRef
# exposes date-range endpoints rather than per-player game logs.
# Approximation: a 162-game season spans ~185 calendar days → ~0.88 games/day.
#   last60g → 68 days  ≈ 60 games
#   last25g → 29 days  ≈ 25 games
#   last5g  →  6 days  ≈  5 games
TIMEFRAME_WINDOWS: dict = {
    "season":  None,
    "last60g": {"days": 68, "min_ab": 50,  "min_ip": 12.0},
    "last25g": {"days": 29, "min_ab": 20,  "min_ip":  7.0},
    "last5g":  {"days":  6, "min_ab":  4,  "min_ip":  1.5},
}

VALID_TIMEFRAMES = list(TIMEFRAME_WINDOWS.keys())

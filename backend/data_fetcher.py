"""
Fetch season-level batting and pitching stats from FanGraphs via pybaseball.
Results are cached to disk (parquet) for CACHE_MAX_AGE_HOURS to avoid
re-downloading on every request.
"""

import time
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

import pybaseball

from config import MIN_AB, MIN_IP, CACHE_MAX_AGE_HOURS, CACHE_DIR

logger = logging.getLogger(__name__)

_cache_dir = Path(CACHE_DIR)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(name: str) -> Path:
    _cache_dir.mkdir(exist_ok=True)
    return _cache_dir / f"{name}.parquet"


def _meta_path(name: str) -> Path:
    _cache_dir.mkdir(exist_ok=True)
    return _cache_dir / f"{name}.meta"


def _is_cache_valid(name: str) -> bool:
    p, m = _cache_path(name), _meta_path(name)
    if not p.exists() or not m.exists():
        return False
    try:
        ts = datetime.fromisoformat(m.read_text().strip())
        return datetime.utcnow() - ts < timedelta(hours=CACHE_MAX_AGE_HOURS)
    except Exception:
        return False


def _save_cache(name: str, df: pd.DataFrame) -> None:
    df.to_parquet(_cache_path(name), index=False)
    _meta_path(name).write_text(datetime.utcnow().isoformat())
    logger.info("Cached %s (%d rows)", name, len(df))


def _load_cache(name: str) -> pd.DataFrame:
    logger.info("Loading %s from disk cache", name)
    return pd.read_parquet(_cache_path(name))


# ── Retry helper ──────────────────────────────────────────────────────────────

def _retry(fn, retries: int = 3, base_delay: float = 2.0):
    """Call fn(); on exception retry with exponential back-off."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, retries, exc)
            if attempt == retries - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))


# ── Public fetch functions ────────────────────────────────────────────────────

def fetch_batting(season: int = 2025) -> pd.DataFrame:
    """Return a DataFrame of batting stats for the given season filtered to AB >= MIN_AB."""
    name = f"batting_{season}"
    if _is_cache_valid(name):
        return _load_cache(name)

    logger.info("Fetching batting stats for %d from FanGraphs…", season)
    # qual=1 → return every player; we filter by AB ourselves
    df: pd.DataFrame = _retry(lambda: pybaseball.batting_stats(season, qual=1))

    required = ["Name", "Team", "AB", "R", "HR", "RBI", "SB", "AVG"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"FanGraphs batting data is missing expected columns: {missing}\n"
            f"Available columns: {list(df.columns)}"
        )

    df = df[required].copy()
    for col in ["AB", "R", "HR", "RBI", "SB", "AVG"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df = df[df["AB"] >= MIN_AB].reset_index(drop=True)
    logger.info("Batting pool: %d players (AB >= %d)", len(df), MIN_AB)

    _save_cache(name, df)
    return df


def fetch_pitching(season: int = 2025) -> pd.DataFrame:
    """Return a DataFrame of pitching stats for the given season filtered to IP >= MIN_IP."""
    name = f"pitching_{season}"
    if _is_cache_valid(name):
        return _load_cache(name)

    logger.info("Fetching pitching stats for %d from FanGraphs…", season)
    df: pd.DataFrame = _retry(lambda: pybaseball.pitching_stats(season, qual=1))

    required = ["Name", "Team", "IP", "SO", "W", "SV", "ERA", "WHIP"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"FanGraphs pitching data is missing expected columns: {missing}\n"
            f"Available columns: {list(df.columns)}"
        )

    # HLD (holds) may not exist for all FanGraphs exports
    if "HLD" not in df.columns:
        logger.warning("HLD column not found – defaulting all holds to 0")
        df["HLD"] = 0

    keep = ["Name", "Team", "IP", "SO", "W", "SV", "HLD", "ERA", "WHIP"]
    df = df[keep].copy()

    for col in ["IP", "SO", "W", "SV", "HLD", "ERA", "WHIP"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df = df[df["IP"] >= MIN_IP].reset_index(drop=True)
    logger.info("Pitching pool: %d pitchers (IP >= %.0f)", len(df), MIN_IP)

    _save_cache(name, df)
    return df

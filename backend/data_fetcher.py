"""
Fetch season-level batting and pitching stats from FanGraphs (full season)
or Baseball Reference (date-range windows) via pybaseball.
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

# Bump this string whenever the schema of cached DataFrames changes.
# Old parquet files use the previous version key and are effectively ignored.
_CACHE_VERSION = "v4"


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(name: str) -> Path:
    _cache_dir.mkdir(exist_ok=True)
    return _cache_dir / f"{name}_{_CACHE_VERSION}.parquet"


def _meta_path(name: str) -> Path:
    _cache_dir.mkdir(exist_ok=True)
    return _cache_dir / f"{name}_{_CACHE_VERSION}.meta"


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


# ── Full-season fetchers (FanGraphs) ──────────────────────────────────────────

def fetch_batting(season: int = 2025) -> pd.DataFrame:
    """Return batting stats for the full season filtered to AB >= MIN_AB."""
    name = f"batting_{season}"
    if _is_cache_valid(name):
        return _load_cache(name)

    logger.info("Fetching batting stats for %d from FanGraphs…", season)
    df: pd.DataFrame = _retry(lambda: pybaseball.batting_stats(season, qual=1))

    required = ["Name", "Team", "AB", "R", "HR", "RBI", "SB", "AVG"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"FanGraphs batting data missing columns: {missing}\n"
            f"Available: {list(df.columns)}"
        )

    df = df[required].copy()
    for col in ["AB", "R", "HR", "RBI", "SB", "AVG"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df = df[df["AB"] >= MIN_AB].reset_index(drop=True)
    logger.info("Batting pool: %d players (AB >= %d)", len(df), MIN_AB)

    _save_cache(name, df)
    return df


def fetch_pitching(season: int = 2025) -> pd.DataFrame:
    """Return pitching stats for the full season filtered to IP >= MIN_IP."""
    name = f"pitching_{season}"
    if _is_cache_valid(name):
        return _load_cache(name)

    logger.info("Fetching pitching stats for %d from FanGraphs…", season)
    df: pd.DataFrame = _retry(lambda: pybaseball.pitching_stats(season, qual=1))

    required = ["Name", "Team", "IP", "SO", "W", "SV", "ERA", "WHIP"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"FanGraphs pitching data missing columns: {missing}\n"
            f"Available: {list(df.columns)}"
        )

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


# ── Date-range fetchers (Baseball Reference) ──────────────────────────────────

def _normalize_bref_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename BRef column variants to our canonical names and clean player names."""
    rename = {}
    # Team column
    if "Tm" in df.columns and "Team" not in df.columns:
        rename["Tm"] = "Team"
    # Batting average
    if "BA" in df.columns and "AVG" not in df.columns:
        rename["BA"] = "AVG"
    if rename:
        df = df.rename(columns=rename)
    # Strip asterisks (*) and hash marks (#) from names (BRef handedness markers)
    if "Name" in df.columns:
        df["Name"] = df["Name"].astype(str).str.replace(r"[*#\\]", "", regex=True).str.strip()
    return df


def fetch_batting_range(start_dt: str, end_dt: str, min_ab: int) -> pd.DataFrame:
    """
    Return batting stats for the given date range filtered to AB >= min_ab.
    Uses Baseball Reference via pybaseball.batting_stats_range().
    Note: AVG comes from BRef's 'BA' column.
    """
    safe_start = start_dt.replace("-", "")
    safe_end = end_dt.replace("-", "")
    name = f"batting_range_{safe_start}_{safe_end}"

    if _is_cache_valid(name):
        return _load_cache(name)

    logger.info("Fetching batting stats %s → %s from BRef…", start_dt, end_dt)
    df: pd.DataFrame = _retry(
        lambda: pybaseball.batting_stats_range(start_dt, end_dt)
    )

    df = _normalize_bref_columns(df)

    required = ["Name", "Team", "AB", "R", "HR", "RBI", "SB", "AVG"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"BRef batting range data missing columns: {missing}\n"
            f"Available: {list(df.columns)}"
        )

    df = df[required].copy()
    for col in ["AB", "R", "HR", "RBI", "SB", "AVG"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df = df[df["AB"] >= min_ab].reset_index(drop=True)
    logger.info(
        "Batting range pool: %d players (AB >= %d, %s → %s)",
        len(df), min_ab, start_dt, end_dt,
    )

    _save_cache(name, df)
    return df


def fetch_pitching_range(start_dt: str, end_dt: str, min_ip: float) -> pd.DataFrame:
    """
    Return pitching stats for the given date range filtered to IP >= min_ip.
    Uses Baseball Reference via pybaseball.pitching_stats_range().
    Note: HLD is NOT available from BRef — it is set to 0 for all pitchers.
    """
    safe_start = start_dt.replace("-", "")
    safe_end = end_dt.replace("-", "")
    name = f"pitching_range_{safe_start}_{safe_end}"

    if _is_cache_valid(name):
        return _load_cache(name)

    logger.info("Fetching pitching stats %s → %s from BRef…", start_dt, end_dt)
    df: pd.DataFrame = _retry(
        lambda: pybaseball.pitching_stats_range(start_dt, end_dt)
    )

    df = _normalize_bref_columns(df)

    required = ["Name", "Team", "IP", "SO", "W", "SV", "ERA", "WHIP"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"BRef pitching range data missing columns: {missing}\n"
            f"Available: {list(df.columns)}"
        )

    # HLD is not available in BRef data
    df["HLD"] = 0

    keep = ["Name", "Team", "IP", "SO", "W", "SV", "HLD", "ERA", "WHIP"]
    df = df[keep].copy()

    for col in ["IP", "SO", "W", "SV", "HLD", "ERA", "WHIP"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df = df[df["IP"] >= min_ip].reset_index(drop=True)
    logger.info(
        "Pitching range pool: %d pitchers (IP >= %.1f, %s → %s)",
        len(df), min_ip, start_dt, end_dt,
    )

    _save_cache(name, df)
    return df

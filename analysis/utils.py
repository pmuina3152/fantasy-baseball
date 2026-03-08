"""
Shared utility helpers used across the analysis pipeline.

Responsibilities:
    - Disk cache read / write / validation  (parquet + .meta timestamp files)
    - Retry wrapper with exponential back-off
    - Player name normalization for cross-source merging
    - MLBAM → FanGraphs player-ID cross-reference (via Chadwick register)
"""

import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pybaseball

from config import CACHE_MAX_AGE_HOURS, CACHE_VERSION, DATA_RAW_DIR

logger = logging.getLogger(__name__)


# ── Disk cache helpers ─────────────────────────────────────────────────────────

def _cache_path(name: str) -> Path:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_RAW_DIR / f"{name}_{CACHE_VERSION}.parquet"


def _meta_path(name: str) -> Path:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_RAW_DIR / f"{name}_{CACHE_VERSION}.meta"


def is_cache_valid(name: str, max_age_hours: int = CACHE_MAX_AGE_HOURS) -> bool:
    """Return True if a fresh cached parquet exists for *name*."""
    p, m = _cache_path(name), _meta_path(name)
    if not p.exists() or not m.exists():
        return False
    try:
        ts = datetime.fromisoformat(m.read_text().strip())
        return datetime.utcnow() - ts < timedelta(hours=max_age_hours)
    except Exception:
        return False


def save_cache(name: str, df: pd.DataFrame) -> None:
    """Persist *df* to disk under *name* and record the timestamp."""
    df.to_parquet(_cache_path(name), index=False)
    _meta_path(name).write_text(datetime.utcnow().isoformat())
    logger.info("Cached '%s' → %d rows", name, len(df))


def load_cache(name: str) -> pd.DataFrame:
    """Load and return the cached parquet for *name*."""
    logger.info("Loading '%s' from disk cache", name)
    return pd.read_parquet(_cache_path(name))


# ── Retry helper ───────────────────────────────────────────────────────────────

def retry(fn, retries: int = 3, base_delay: float = 2.0):
    """
    Call fn() and retry on any exception with exponential back-off.

    Args:
        fn:          Zero-argument callable to attempt.
        retries:     Maximum number of attempts.
        base_delay:  Seconds to wait after first failure; doubles each retry.

    Returns:
        Whatever fn() returns on success.

    Raises:
        The last exception raised by fn() after all retries are exhausted.
    """
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, retries, exc)
            if attempt == retries - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))


# ── Player name normalization ──────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """
    Produce a lowercase ASCII key from a player name for cross-source matching.

    Handles:
        - BRef handedness markers (* and #)
        - Unicode accent characters (é → e, ñ → n, etc.)
        - Hyphens and apostrophes in compound names
        - Common suffixes (Jr, Sr, II, III, IV)
        - Extra whitespace

    Examples:
        "Yordan Álvarez"    → "yordan alvarez"
        "Vladimir Guerrero Jr.*" → "vladimir guerrero"
        "Michael A. Taylor"  → "michael a taylor"
    """
    if not isinstance(name, str):
        name = str(name)

    # Remove BRef handedness / special markers
    name = re.sub(r"[*#\\]", "", name)

    # Decompose unicode characters to base + combining marks, then strip combining
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))

    # Lower-case
    name = name.lower()

    # Remove apostrophes (e.g., "O'Neill" → "oneill")
    name = name.replace("'", "")

    # Replace hyphens with space so compound names align across sources
    name = name.replace("-", " ")

    # Remove anything that isn't a letter, digit, or space
    name = re.sub(r"[^a-z0-9\s]", "", name)

    # Strip common suffixes that appear in some sources but not others
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", name)

    # Collapse whitespace
    return " ".join(name.split())


# ── MLBAM → FanGraphs player-ID map ───────────────────────────────────────────

_MLBAM_TO_FG_CACHE: dict[int, int] = {}  # module-level in-memory cache


def get_mlbam_to_fangraphs_map() -> dict[int, int]:
    """
    Return a dict mapping MLBAM integer player ID → FanGraphs integer player ID.

    Uses the Chadwick player register (pybaseball.chadwick_register).
    The register is cached to disk for 7 days (it rarely changes mid-season).

    Returns an empty dict and logs a warning if the download fails; downstream
    code falls back to name-based matching in that case.
    """
    global _MLBAM_TO_FG_CACHE

    if _MLBAM_TO_FG_CACHE:
        return _MLBAM_TO_FG_CACHE

    cache_name = "chadwick_register"
    if is_cache_valid(cache_name, max_age_hours=24 * 7):
        reg = load_cache(cache_name)
    else:
        logger.info("Downloading Chadwick player register…")
        try:
            # Note: do NOT pass use_bref_id — that argument was removed in
            # current pybaseball versions and raises a TypeError.
            reg = retry(lambda: pybaseball.chadwick_register())
            save_cache(cache_name, reg)
        except Exception as exc:
            logger.warning(
                "Chadwick register download failed (%s). "
                "Falling back to name-only player matching.",
                exc,
            )
            return {}

    mlbam_col = next((c for c in ["key_mlbam", "mlbam_id"] if c in reg.columns), None)
    fg_col    = next((c for c in ["key_fangraphs", "fg_id"] if c in reg.columns), None)

    if mlbam_col is None or fg_col is None:
        logger.warning(
            "Chadwick register columns unexpected: %s. Skipping ID map.",
            list(reg.columns),
        )
        return {}

    sub = reg[[mlbam_col, fg_col]].dropna()
    _MLBAM_TO_FG_CACHE = {
        int(r[mlbam_col]): int(r[fg_col])
        for _, r in sub.iterrows()
        if pd.notna(r[mlbam_col]) and pd.notna(r[fg_col])
    }
    logger.info("MLBAM → FanGraphs ID map: %d entries", len(_MLBAM_TO_FG_CACHE))
    return _MLBAM_TO_FG_CACHE


# ── FanGraphs player-ID normalization ────────────────────────────────────────

def normalize_fg_id(series: pd.Series) -> pd.Series:
    """
    Coerce a FanGraphs player-ID column to pandas nullable **Int64**.

    This is the single canonical function every module calls before using
    fg_id as a merge key.  Calling it on BOTH sides of every merge guarantees
    identical dtypes and prevents the
    "merging on int64 and object columns" error.

    Handles all real-world source dtypes:
        float64  (NaN where missing)          → Int64 with pd.NA
        object   (mix of Python int/None/str) → Int64 with pd.NA
        int64    (no NaN support)             → Int64
        "nan", "", None, 0                   → pd.NA
                                               (0 is never a valid FG player ID)
    """
    # Convert everything to numeric first so "nan" / "" / None all become NaN
    s = pd.to_numeric(series, errors="coerce")
    # Cast to pandas nullable integer — the only int dtype that supports pd.NA
    s = s.astype("Int64")
    # Treat 0 as missing (FanGraphs never assigns player ID 0)
    s = s.where(s != 0, other=pd.NA)
    return s


# ── DataFrame helpers ─────────────────────────────────────────────────────────

def to_numeric_safe(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Coerce *cols* to numeric in-place, filling non-parseable values with NaN."""
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def clean_for_json(obj):
    """
    Recursively replace NaN / Inf with None so the object is JSON-serialisable.
    Works on dicts, lists, and scalar numpy/pandas types.
    """
    import math
    import numpy as np

    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_for_json(v) for v in obj]
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj

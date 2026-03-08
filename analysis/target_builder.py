"""
Build the target variable table for the year-over-year hitter modeling pipeline.

Pulls FULL-SEASON FanGraphs batting stats for the target year and extracts the
five fantasy-relevant target variables:
    HR, R, RBI, SB, AVG

Columns are prefixed with "next_" to make the year-over-year direction explicit
in the merged modeling dataset.

Data source:
    pybaseball.batting_stats(target_season, qual=1)

This replaces the previous design that pulled Baseball Reference date-range
data (batting_stats_range) for a second-half window.  BRef range scraping is
brittle and was producing "list index out of range" errors.

Using FanGraphs full-season data for targets is:
    • Reliable  — same endpoint used for predictor features, no new source
    • Consistent — same player-ID (IDfg) available for cross-season merging
    • Accurate   — full-season totals are the actual fantasy production we want

API endpoint note:
    A future /api/analysis/targets?season=2025 endpoint would call
    build_targets() to return next-year production actuals for a cohort.
"""

import logging

import numpy as np
import pandas as pd

from config import TARGET_STATS
from data_sources import fetch_fg_batting_full
from utils import normalize_fg_id, normalize_name, to_numeric_safe

logger = logging.getLogger(__name__)

# FanGraphs columns we need for targets and context
_FG_TARGET_COLS = {
    "HR":   "HR",   # home runs
    "R":    "R",    # runs
    "RBI":  "RBI",  # runs batted in
    "SB":   "SB",   # stolen bases
    "AVG":  "AVG",  # batting average
    "PA":   "PA",   # plate appearances (context / for target PA filter)
    "AB":   "AB",   # at-bats (used to recompute AVG accurately)
    "H":    "H",    # hits (used to recompute AVG accurately)
}

# Player identity columns from FanGraphs
_FG_ID_COL_CANDIDATES   = ["IDfg", "playerid", "FG_ID"]
_FG_NAME_COL            = "Name"
_FG_TEAM_COL            = "Team"


def build_targets(target_season: int) -> pd.DataFrame:
    """
    Build the next-season target table for a single target year.

    Args:
        target_season: The MLB season year whose production becomes the target.

    Returns:
        DataFrame — one row per qualifying player — with columns:
            target_season, fg_id, norm_name,
            next_HR, next_R, next_RBI, next_SB, next_AVG,
            next_PA  (context; used for the target-season PA filter)
    """
    logger.info("=== Building targets | target_season=%d ===", target_season)

    fg_raw = fetch_fg_batting_full(target_season)
    df = _extract_targets(fg_raw, target_season)

    logger.info(
        "Targets done: target_season=%d | %d players",
        target_season, len(df),
    )
    return df


def _extract_targets(fg_df: pd.DataFrame, target_season: int) -> pd.DataFrame:
    """Extract and rename target columns from a FanGraphs batting DataFrame."""

    # ── Player identity ───────────────────────────────────────────────────────
    fg_id_col = next((c for c in _FG_ID_COL_CANDIDATES if c in fg_df.columns), None)

    df = fg_df.copy()

    if fg_id_col:
        # normalize_fg_id coerces to pandas nullable Int64, matching the dtype
        # used by feature_builder so the cross-season merge never type-errors.
        df["fg_id"] = normalize_fg_id(df[fg_id_col])
    else:
        logger.warning(
            "FanGraphs target data for %d has no IDfg column — will fall back "
            "to name-based merging.", target_season
        )
        df["fg_id"] = pd.array([pd.NA] * len(df), dtype="Int64")

    if _FG_NAME_COL in df.columns:
        df["norm_name"] = df[_FG_NAME_COL].astype(str).str.strip().apply(normalize_name)
    else:
        df["norm_name"] = ""

    df["target_season"] = target_season

    # ── Coerce target columns to numeric ─────────────────────────────────────
    numeric_cols = [c for c in _FG_TARGET_COLS.keys() if c in df.columns]
    df = to_numeric_safe(df, numeric_cols)

    # ── Recompute AVG from H / AB for accuracy ─────────────────────────────
    # FanGraphs rounds AVG; recomputing from raw H/AB avoids truncation error.
    if "AB" in df.columns and "H" in df.columns:
        df["AVG"] = np.where(
            df["AB"].fillna(0) > 0,
            df["H"].fillna(0) / df["AB"].fillna(1),
            0.0,
        )
    elif "AVG" not in df.columns:
        logger.warning(
            "Target season %d: neither AVG nor H/AB found; next_AVG will be NaN.",
            target_season,
        )
        df["AVG"] = np.nan

    # ── Fill missing counting stats with 0 ───────────────────────────────────
    for col in ["HR", "R", "RBI", "SB"]:
        if col in df.columns:
            df[col] = df[col].fillna(0)
        else:
            logger.warning(
                "Target '%s' absent in season %d — filling 0.", col, target_season
            )
            df[col] = 0

    # ── Rename with "next_" prefix ────────────────────────────────────────────
    rename = {stat: f"next_{stat}" for stat in TARGET_STATS if stat in df.columns}
    if "PA" in df.columns:
        rename["PA"] = "next_PA"
    df = df.rename(columns=rename)

    # ── Column selection ───────────────────────────────────────────────────────
    keep = ["target_season", "fg_id", "norm_name"]
    keep += [f"next_{s}" for s in TARGET_STATS if f"next_{s}" in df.columns]
    if "next_PA" in df.columns:
        keep.append("next_PA")

    df = (
        df[keep]
        .drop_duplicates(subset=["target_season", "fg_id"], keep="first")
        .reset_index(drop=True)
    )

    # ── Coverage report ───────────────────────────────────────────────────────
    for col in [f"next_{s}" for s in TARGET_STATS]:
        n_nan = df[col].isna().sum() if col in df.columns else 0
        if n_nan:
            logger.warning(
                "Target '%s' (season %d): %d NaN values.",
                col, target_season, n_nan,
            )

    return df

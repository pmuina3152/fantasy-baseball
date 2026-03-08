"""
Build the predictor feature table for the year-over-year hitter modeling pipeline.

Takes full-season data from three reliable sources and assembles one row per
player per predictor season containing only approved process/skill variables.

Sources:
    1. FanGraphs full-season  [FG]  → plate discipline, batted-ball profile,
                                       EV, barrel%, launch angle, PA, age
    2. Statcast EV/barrel     [SC]  → supplements sweet_spot_pct and any EV
                                       columns missing from FG
    3. Sprint speed           [SP]  → sprint_speed (ft/sec)

No BRef date-range scraping is used.  All sources are full-season aggregated
leaderboards available reliably from pybaseball.

Merge strategy:
    • FanGraphs is the anchor table (provides IDfg = stable cross-season key).
    • Statcast rows are joined first by MLBAM→FG ID (Chadwick register),
      with normalised player name as a fallback.
    • Sprint speed rows are joined by the same two-pass strategy.
    • Multi-team FG rows: keep the one with the most PA (FG often has one
      combined row already, but we deduplicate defensively).

NOTE — half-season split design:
    The previous version of this file used pybaseball.batting_stats_range()
    (BRef scraping) to obtain true first-half BB% / K% and PA counts.  That
    was replaced with FanGraphs full-season values because:
      (a) BRef range scraping throws "list index out of range" errors reliably,
      (b) full-season FG rates are already available and more stable.
    If first-half-only metrics are needed in the future, derive them from raw
    Statcast pitch-level data (pybaseball.statcast(start_dt, end_dt)).
"""

import logging

import numpy as np
import pandas as pd

from config import ALL_PREDICTORS, EXCLUDED_FROM_PREDICTORS
from data_sources import (
    fetch_fg_batting_full,
    fetch_sprint_speed,
    fetch_statcast_ev_barrels,
)
from utils import get_mlbam_to_fangraphs_map, normalize_fg_id, normalize_name

logger = logging.getLogger(__name__)


# ── FanGraphs column → clean feature name ─────────────────────────────────────
# Listed in priority order: first match for a given feature name wins.
# Key  = exact FanGraphs column name from batting_stats()
# Value = snake_case name from config.ALL_PREDICTORS

_FG_COL_MAP: list[tuple[str, str]] = [
    # Plate discipline
    ("BB%",        "bb_pct"),
    ("K%",         "k_pct"),
    ("O-Swing%",   "o_swing_pct"),
    ("Z-Swing%",   "z_swing_pct"),
    ("Swing%",     "swing_pct"),
    ("O-Contact%", "o_contact_pct"),
    ("Z-Contact%", "z_contact_pct"),
    ("Contact%",   "contact_pct"),
    ("Whiff%",     "whiff_pct"),   # preferred; newer FG metric
    ("SwStr%",     "whiff_pct"),   # fallback if Whiff% absent
    # Batted ball
    ("GB%",        "gb_pct"),
    ("FB%",        "fb_pct"),
    ("LD%",        "ld_pct"),
    ("Pull%",      "pull_pct"),
    ("Cent%",      "cent_pct"),
    ("Oppo%",      "oppo_pct"),
    # Contact quality (FG embeds Statcast metrics for 2015+)
    ("HardHit%",   "hard_hit_pct"),  # Statcast-sourced, preferred
    ("Hard%",      "hard_hit_pct"),  # older BIS metric, fallback
    ("EV",         "avg_exit_velocity"),
    ("maxEV",      "max_exit_velocity"),
    ("LA",         "launch_angle_avg"),
    ("Barrel%",    "barrel_pct"),
    # Opportunity / context
    ("PA",         "pa_predictor_season"),  # full-season PA in predictor year
    ("Age",        "age"),
]

# ── Statcast EV/barrel column → feature name ──────────────────────────────────
# Column names from statcast_batter_exitvelo_barrels() vary across pybaseball
# versions; we try multiple known variants with the same priority logic.
_SC_COL_MAP: list[tuple[str, str]] = [
    ("avg_hit_speed",         "avg_exit_velocity"),
    ("avg_exit_velocity",     "avg_exit_velocity"),
    ("max_hit_speed",         "max_exit_velocity"),
    ("max_exit_velocity",     "max_exit_velocity"),
    ("avg_hit_angle",         "launch_angle_avg"),
    ("launch_angle_avg",      "launch_angle_avg"),
    ("anglesweetspotpercent", "sweet_spot_pct"),
    ("sweet_spot_pct",        "sweet_spot_pct"),
    ("brl_percent",           "barrel_pct"),
    ("barrel_pct",            "barrel_pct"),
    ("ev95percent",           "hard_hit_pct"),   # EV ≥ 95 mph ≈ HardHit%
    ("ev95plus",              "hard_hit_pct"),
    ("hard_hit_pct",          "hard_hit_pct"),
]

_SP_SPEED_CANDIDATES   = ["sprint_speed", "hp_to_1b"]
_MLBAM_COL_CANDIDATES  = ["player_id", "batter", "mlbam_id"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_decimal(series: pd.Series) -> pd.Series:
    """Normalise a percentage column to [0, 1].  FanGraphs is inconsistent."""
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().mean() > 1.5:
        s = s / 100.0
    return s


# ── Step 1: extract FanGraphs features ────────────────────────────────────────

def _extract_fg_features(fg_df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename FanGraphs columns to snake_case feature names, normalise percentages,
    and attach player identity columns (fg_id, norm_name, name_raw_fg, team_fg).
    """
    fg_id_col = next(
        (c for c in ["IDfg", "playerid", "FG_ID"] if c in fg_df.columns), None
    )

    # Build feature → fg_col mapping (first match wins)
    present: dict[str, str] = {}
    for fg_col, feat_name in _FG_COL_MAP:
        if fg_col in fg_df.columns and feat_name not in present:
            present[feat_name] = fg_col

    found   = [f for f in ALL_PREDICTORS if f in present]
    missing = [f for f in ALL_PREDICTORS if f not in present]
    if missing:
        logger.info(
            "FG %d: features found=%d, absent (SC/SP will fill)=%d: %s",
            fg_df.get("Season", pd.Series([0])).iloc[0] if "Season" in fg_df.columns else 0,
            len(found), len(missing), missing,
        )

    rename = {v: k for k, v in present.items()}
    df = fg_df.rename(columns=rename).copy()

    # Player identity — normalize to pandas nullable Int64 so all downstream
    # merges see a consistent dtype regardless of what FanGraphs returns.
    if fg_id_col:
        df["fg_id"] = normalize_fg_id(df[fg_id_col])
    else:
        df["fg_id"] = pd.array([pd.NA] * len(df), dtype="Int64")

    df["name_raw_fg"] = df["Name"].astype(str).str.strip() if "Name" in df.columns else ""
    df["norm_name"]   = df["name_raw_fg"].apply(normalize_name)
    df["team_fg"]     = df["Team"].astype(str).str.strip() if "Team" in df.columns else ""

    # Normalise percentage columns to [0, 1]
    pct_cols = [
        "bb_pct", "k_pct", "o_swing_pct", "z_swing_pct", "swing_pct",
        "o_contact_pct", "z_contact_pct", "contact_pct", "whiff_pct",
        "gb_pct", "fb_pct", "ld_pct", "pull_pct", "cent_pct", "oppo_pct",
        "hard_hit_pct", "barrel_pct", "sweet_spot_pct",
    ]
    for col in pct_cols:
        if col in df.columns:
            df[col] = _to_decimal(df[col])

    # Coerce PA and Age to numeric
    for col in ("pa_predictor_season", "age"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Deduplicate: keep row with most PA per player (handles rare FG dupes)
    if "pa_predictor_season" in df.columns:
        df = (df.sort_values("pa_predictor_season", ascending=False)
                .drop_duplicates(subset=["norm_name"], keep="first"))
    else:
        df = df.drop_duplicates(subset=["norm_name"], keep="first")

    return df.reset_index(drop=True)


# ── Step 2: Statcast EV / barrel supplement ───────────────────────────────────

def _extract_sc_ev(sc_df: pd.DataFrame, mlbam_to_fg: dict) -> pd.DataFrame:
    """
    Extract EV / barrel / launch angle / sweet_spot_pct from the Statcast
    leaderboard.  Returns: fg_id, norm_name, <available SC features>.
    Used only to fill NaN cells that FanGraphs didn't supply.
    """
    if sc_df.empty:
        return pd.DataFrame(columns=["fg_id", "norm_name"])

    mlbam_col = next((c for c in _MLBAM_COL_CANDIDATES if c in sc_df.columns), None)

    present: dict[str, str] = {}
    for sc_col, feat_name in _SC_COL_MAP:
        if sc_col in sc_df.columns and feat_name not in present:
            present[feat_name] = sc_col

    rename = {v: k for k, v in present.items()}
    df = sc_df.rename(columns=rename).copy()

    # Map MLBAM → FanGraphs ID, then normalize to Int64
    if mlbam_col:
        raw_ids = df[mlbam_col].apply(
            lambda x: mlbam_to_fg.get(int(x)) if pd.notna(x) else None
        )
    else:
        raw_ids = pd.Series([None] * len(df), index=df.index)
    df["fg_id"] = normalize_fg_id(raw_ids)

    last_c  = next((c for c in ["last_name",  "name_last"]  if c in df.columns), None)
    first_c = next((c for c in ["first_name", "name_first"] if c in df.columns), None)
    if last_c and first_c:
        df["norm_name"] = (
            df[first_c].fillna("").astype(str) + " " +
            df[last_c].fillna("").astype(str)
        ).apply(normalize_name)
    else:
        df["norm_name"] = ""

    for col in ("barrel_pct", "hard_hit_pct", "sweet_spot_pct"):
        if col in df.columns:
            df[col] = _to_decimal(df[col])

    feat_cols = [c for c in present.keys() if c in df.columns]
    return (
        df[["fg_id", "norm_name"] + feat_cols]
        .drop_duplicates(subset=["norm_name"], keep="first")
        .reset_index(drop=True)
    )


# ── Step 3: Sprint speed ──────────────────────────────────────────────────────

def _extract_sprint(sp_df: pd.DataFrame, mlbam_to_fg: dict) -> pd.DataFrame:
    """Extract sprint_speed (ft/sec).  Returns: fg_id, norm_name, sprint_speed."""
    if sp_df.empty:
        return pd.DataFrame(columns=["fg_id", "norm_name", "sprint_speed"])

    mlbam_col = next((c for c in _MLBAM_COL_CANDIDATES if c in sp_df.columns), None)
    speed_col = next((c for c in _SP_SPEED_CANDIDATES  if c in sp_df.columns), None)

    if speed_col is None:
        logger.warning(
            "No sprint speed column found. Columns present: %s", list(sp_df.columns)
        )
        return pd.DataFrame(columns=["fg_id", "norm_name", "sprint_speed"])

    df = sp_df.copy()
    df["sprint_speed"] = pd.to_numeric(df[speed_col], errors="coerce")

    # Map MLBAM → FanGraphs ID, then normalize to Int64
    if mlbam_col:
        raw_ids = df[mlbam_col].apply(
            lambda x: mlbam_to_fg.get(int(x)) if pd.notna(x) else None
        )
    else:
        raw_ids = pd.Series([None] * len(df), index=df.index)
    df["fg_id"] = normalize_fg_id(raw_ids)

    last_c  = next((c for c in ["last_name",  "name_last"]  if c in df.columns), None)
    first_c = next((c for c in ["first_name", "name_first"] if c in df.columns), None)
    if last_c and first_c:
        df["norm_name"] = (
            df[first_c].fillna("").astype(str) + " " +
            df[last_c].fillna("").astype(str)
        ).apply(normalize_name)
    else:
        df["norm_name"] = ""

    return (
        df[["fg_id", "norm_name", "sprint_speed"]]
        .drop_duplicates(subset=["norm_name"], keep="first")
        .reset_index(drop=True)
    )


# ── Supplement helper ─────────────────────────────────────────────────────────

def _supplement_with(base: pd.DataFrame, supplement: pd.DataFrame) -> pd.DataFrame:
    """
    Fill NaN cells in *base* from *supplement* using a two-pass merge:
        Pass 1: join on fg_id  (reliable, preferred)
        Pass 2: join on norm_name (fallback for unmatched rows)

    Only fills; never overwrites existing non-NaN values.
    Columns in *supplement* that don't exist in *base* are added as new columns.
    """
    meta = {"fg_id", "norm_name", "name_raw_fg", "team_fg", "predictor_season"}
    sup_feat_cols = [c for c in supplement.columns if c not in meta]

    for col in sup_feat_cols:
        if col not in base.columns:
            base[col] = np.nan

    def _fill_pass(left: pd.DataFrame, right: pd.DataFrame, key: str) -> pd.DataFrame:
        if key not in left.columns or key not in right.columns:
            return left
        right_clean = right[[key] + sup_feat_cols].drop_duplicates(subset=[key])
        merged = left.merge(right_clean, on=key, how="left", suffixes=("", "_sup"))
        for col in sup_feat_cols:
            sup_col = col + "_sup"
            if sup_col in merged.columns:
                merged[col] = merged[col].combine_first(merged[sup_col])
                merged.drop(columns=[sup_col], inplace=True)
        return merged

    base = _fill_pass(base, supplement, "fg_id")
    base = _fill_pass(base, supplement, "norm_name")
    return base


# ── Public entry point ────────────────────────────────────────────────────────

def build_predictor_features(predictor_season: int) -> pd.DataFrame:
    """
    Build the predictor feature table for one season.

    Args:
        predictor_season: The MLB season year whose stats become predictor inputs.

    Returns:
        DataFrame — one row per player — with columns:
            predictor_season, fg_id, norm_name, name_raw_fg, team_fg,
            <all features in config.ALL_PREDICTORS>

        Missing features (source didn't have the column) are NaN;
        they are imputed in dataset_builder.py.

    API endpoint note:
        A future /api/analysis/features?season=2024 endpoint would call this
        function to return the skill-profile snapshot for any given season.
    """
    logger.info("=== Building predictor features | season=%d ===", predictor_season)

    # ── Fetch raw sources ──────────────────────────────────────────────────────
    fg_raw = fetch_fg_batting_full(predictor_season)
    sc_raw = fetch_statcast_ev_barrels(predictor_season)
    sp_raw = fetch_sprint_speed(predictor_season)
    mlbam_to_fg = get_mlbam_to_fangraphs_map()

    # ── Extract and transform ──────────────────────────────────────────────────
    fg_feat = _extract_fg_features(fg_raw)
    sc_feat = _extract_sc_ev(sc_raw, mlbam_to_fg)
    sp_feat = _extract_sprint(sp_raw, mlbam_to_fg)

    logger.info(
        "Extracted rows — FG: %d | SC: %d | Sprint: %d",
        len(fg_feat), len(sc_feat), len(sp_feat),
    )

    # ── Anchor on FG; supplement from SC and sprint speed ─────────────────────
    df = fg_feat.copy()
    df = _supplement_with(df, sc_feat)
    df = _supplement_with(df, sp_feat)

    # ── Guard against excluded outcome columns ────────────────────────────────
    bad = [c for c in df.columns if c.lower() in EXCLUDED_FROM_PREDICTORS]
    if bad:
        logger.warning("Dropping excluded outcome columns: %s", bad)
        df.drop(columns=bad, inplace=True)

    # ── Tag with predictor season ─────────────────────────────────────────────
    df["predictor_season"] = predictor_season

    # ── Ensure all expected feature columns are present ───────────────────────
    for col in ALL_PREDICTORS:
        if col not in df.columns:
            logger.debug("Feature '%s' absent for season %d — NaN.", col, predictor_season)
            df[col] = np.nan

    # ── Final column selection ─────────────────────────────────────────────────
    identity = ["predictor_season", "fg_id", "norm_name", "name_raw_fg", "team_fg"]
    keep = identity + ALL_PREDICTORS
    df = df[[c for c in keep if c in df.columns]].reset_index(drop=True)

    n_missing = df[ALL_PREDICTORS].isna().any(axis=1).sum()
    logger.info(
        "Predictor features done: season=%d | %d players | %d features | "
        "%d players have ≥1 NaN feature (will be imputed)",
        predictor_season, len(df), len(ALL_PREDICTORS), n_missing,
    )
    return df

"""
2026 Hitter Projection Engine
==============================

Projects HR, R, RBI, SB, and AVG for the upcoming season using a weighted
multi-year skill model:

    weighted_predictor = 0.5 × 2025 + 0.3 × 2024 + 0.2 × 2023

Steps:
    1. Fetch full-season FanGraphs skill stats for 2023, 2024, 2025.
    2. Compute recency-weighted predictor values per player.
    3. Z-score each weighted predictor against the 2025-qualified player pool.
    4. Compute a category skill score (weighted sum of predictor z-scores).
    5. Project rate = pool_mean + sqrt(R²) × pool_std × skill_score.
       AVG uses a separate z-score rescaling path (see AVG_TARGET_STD below).
    6. Project PA  = 0.7 × PA_2025 + 0.3 × PA_2024  (clipped to [100, 700]).
    7. Projected totals = rate × projected_PA.
    8. Pass projected totals through the existing compute_hitter_zscores() so
       projected fantasy z-scores are computed identically to actual rankings.

Calibration source:
    sqrt(R²) values come from analysis/results/csv/rate_model_performance_summary.csv
    (leave-one-season-out ElasticNet CV).

AVG calibration note:
    The generic sqrt(R²) × pool_std formula compresses AVG projections severely
    because pool_std ≈ 0.034 and skill scores rarely exceed ±1.5.  AVG uses a
    dedicated z-score rescaling path (_project_avg_calibrated) that:
      • Normalises skill_AVG to N(0,1) across the current player pool.
      • Scales to a target distribution anchored at the 2025 pool mean with
        AVG_TARGET_STD (0.025) — reflecting realistic regression-to-mean spread
        while still separating elite contact specialists from power hitters.

TUNING POINT:
    All category weights live in PROJECTION_WEIGHTS below — one dict, no magic.

Reusability note:
    build_hitter_projections() returns a plain DataFrame.  A future
    GET /api/players/grouped?mode=projection endpoint could feed it into
    the existing group_by_team helper for Team Builder / Trade Analyzer.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ── Optional pybaseball ────────────────────────────────────────────────────────
# On Vercel, pybaseball is not installed (excluded from root requirements.txt to
# keep the serverless bundle within size limits).  All skill data is served from
# pre-committed parquet files in backend/cache/.  A cache miss on Vercel raises a
# clear RuntimeError rather than silently failing.
try:
    import pybaseball
    _HAS_PYBASEBALL = True
except ImportError:
    pybaseball = None  # type: ignore[assignment]
    _HAS_PYBASEBALL = False

from config import CACHE_DIR, CACHE_MAX_AGE_HOURS, ON_VERCEL
from zscore import compute_hitter_zscores

logger = logging.getLogger(__name__)

# ── Cache settings ─────────────────────────────────────────────────────────────
_cache_dir = Path(CACHE_DIR)
_CACHE_VERSION = "proj_v2"   # v2: adds 'bbe' (BBE from FG Events) for stabilization

# ── Season / weighting config ──────────────────────────────────────────────────
PROJECTION_YEAR   = 2026
PREDICTOR_SEASONS = [2023, 2024, 2025]
SEASON_WEIGHTS    = {2023: 0.2, 2024: 0.3, 2025: 0.5}
MIN_PA_QUALIFY    = 100   # player must have ≥ 100 PA in 2025 to receive a projection

# ── Calibration coefficients ───────────────────────────────────────────────────
# sqrt(R²) from the leave-one-season-out ElasticNet CV reported in
# analysis/results/csv/rate_model_performance_summary.csv.
# Meaning: 1 std-dev of skill score moves projected rate by SQRT_R2 × pool_std.
_SQRT_R2: dict[str, float] = {
    "HR_rate":  0.65,   # sqrt(0.447)
    "R_rate":   0.40,   # sqrt(0.157)
    "RBI_rate": 0.44,   # sqrt(0.200)
    "SB_rate":  0.34,   # sqrt(0.119)
    # AVG is NOT projected via this formula — see _project_avg_calibrated()
}

# ── AVG-specific calibration ───────────────────────────────────────────────────
# The generic sqrt(R²) × pool_std formula is not used for AVG because:
#   • pool_std ≈ 0.034 × sqrt_r2 ≈ 0.50 → max range only ±0.026 from mean
#   • skill_AVG rarely exceeds ±1.5, so elite hitters are stuck near .266 ceiling
#
# Instead: z-normalise skill_AVG → scale to this target spread.
# Actual 2025 pool std ≈ 0.034; AVG_TARGET_STD = 0.025 reflects regression
# to the mean (25% shrinkage toward league average, appropriate for 1-year ahead).
#
# Result at typical skill extremes (pool_mean ≈ 0.240), before clipping:
#   skill_z = +2.4  →  0.240 + 0.025 × 2.4 = .300  (elite; clipped at .320)
#   skill_z = +1.0  →  0.240 + 0.025 × 1.0 = .265  (above-average AVG)
#   skill_z =  0.0  →  0.240                = .240  (league median)
#   skill_z = -2.0  →  0.240 - 0.025 × 2.0 = .190  (clipped at floor .200)
AVG_TARGET_STD: float = 0.025

# ── Rate variance scaling factors ─────────────────────────────────────────────
# Applied AFTER projected rates are computed but BEFORE multiplying by PA.
# Formula:  scaled_rate = league_mean + factor × (projected_rate − league_mean)
#
# Effect: stretches the projected-rate distribution around its own mean so the
# resulting counting-stat leaderboards reach realistic MLB totals.  Player
# ordering is fully preserved — only the spread widens, not the rankings.
#
# Calibrated so that:
#   HR  max ≈ 45–55   (elite sluggers)
#   R   max ≈ 120–140
#   RBI max ≈ 120–140
#   SB  max ≈ 35–50   (elite speedsters)
#
# AVG is intentionally excluded — it uses its own _project_avg_calibrated() path.
# TUNING POINT: adjust these factors if leaderboard totals drift over time.
RATE_SCALE_FACTORS: dict[str, float] = {
    # Calibrated to hit realistic MLB leaderboard totals given
    # the regression-to-mean effect of stabilization + sqrt(R²) compression.
    # R and SB need larger factors because their pre-scale rate distributions
    # are very tight (low sqrt(R²) values → little separation between players).
    "HR_rate":  1.35,   # HR max ≈ 54   (target 45–55)
    "R_rate":   3.00,   # R  max ≈ 120  (target 120–140)
    "RBI_rate": 1.65,   # RBI max ≈ 126 (target 120–140)
    "SB_rate":  4.00,   # SB max ≈ 39   (target 35–50)
}

# ── Stabilization / shrinkage constants ───────────────────────────────────────
# Applied per-season BEFORE recency weighting.  Formula:
#   stabilized = (player_stat × n + league_avg × k) / (n + k)
# where n = observed sample size, k = stabilization constant.
#
# k interpretation: a player with exactly k observations is projected 50%
# toward the league mean.  Larger k = more conservative / more regression.
#
# Two sample-size sources:
#   "pa"  — plate appearances  → discipline/contact stats (K%, BB%, Contact%, etc.)
#   "bbe" — batted ball events (FanGraphs "Events" column)
#             → batted-ball/power stats (Barrel%, EV, LD%, GB%, etc.)
#   If "bbe" column is absent from the cached data (e.g. after a hard clear),
#   the code automatically falls back to "pa" and logs a warning.
#
# "age" is intentionally excluded — no shrinkage for age.
# TUNING POINT: all k values are here, easy to adjust.
STABILIZATION_K: dict[str, tuple[str, float]] = {
    # ── Discipline / contact (sample = PA) ────────────────────────────────────
    "k_pct":           ("pa",  150),
    "bb_pct":          ("pa",  150),
    "contact_pct":     ("pa",  200),
    "z_contact_pct":   ("pa",  200),
    "o_contact_pct":   ("pa",  200),
    "swing_pct":       ("pa",  200),
    "o_swing_pct":     ("pa",  200),
    "z_swing_pct":     ("pa",  200),
    "whiff_pct":       ("pa",  200),
    # ── Power / batted-ball (sample = BBE; fallback to PA if BBE missing) ─────
    "barrel_pct":        ("bbe", 250),
    "hard_hit_pct":      ("bbe", 250),
    "avg_exit_velocity": ("bbe", 200),
    "max_exit_velocity": ("bbe", 300),
    "launch_angle_avg":  ("bbe", 250),
    "ld_pct":            ("bbe", 250),
    "gb_pct":            ("bbe", 250),
    "fb_pct":            ("bbe", 250),
    "pull_pct":          ("bbe", 250),
    "cent_pct":          ("bbe", 250),
    "oppo_pct":          ("bbe", 250),
    # ── Speed (light shrinkage — sprint speed stabilises faster than rates) ───
    "sprint_speed":      ("pa",  100),
    # Not included: age (never shrunk)
}

# ── Category predictor weights ─────────────────────────────────────────────────
# Positive weight  → higher value of that predictor is better for this category.
# Negative weight  → lower value of that predictor is better (k_pct for AVG, etc.)
# Informed by:
#   • analysis/results/csv/rate_random_forest_importances.csv (RF importances)
#   • analysis/results/csv/rate_elastic_net_features.csv      (ElasticNet coefficients)
#   • User specification of "core" vs "secondary" predictors per category
#
# Core predictors carry ~3–4× the weight of secondary predictors.
PROJECTION_WEIGHTS: dict[str, dict[str, float]] = {
    # ── HR per PA ─────────────────────────────────────────────────────────────
    # Driven by raw power: barrel rate and exit velocity dominate.
    "HR_rate": {
        "barrel_pct":          0.30,   # core  — RF #1 (0.174)
        "hard_hit_pct":        0.20,   # core  — RF #2 (0.102)
        "avg_exit_velocity":   0.15,   # core  — RF #3 (0.098)
        "max_exit_velocity":   0.10,   # core  — RF #4 (0.085)
        "fb_pct":              0.08,   # core  — fly balls become HRs
        "launch_angle_avg":    0.07,   # core  — higher angle → more HRs
        "pull_pct":            0.04,   # secondary — pull power to short porch
        "bb_pct":              0.04,   # secondary — patience → better counts
        "k_pct":              -0.02,   # secondary — high K% slightly hurts HR
    },
    # ── R per PA ──────────────────────────────────────────────────────────────
    # On-base ability and speed create the most runs scored.
    "R_rate": {
        "bb_pct":              0.30,   # core — getting on base
        "contact_pct":         0.25,   # core — staying alive, putting ball in play
        "sprint_speed":        0.20,   # core — taking extra bases (user: core)
        "hard_hit_pct":        0.12,   # secondary
        "fb_pct":              0.08,   # secondary — deep flies → tag/score
        "avg_exit_velocity":   0.05,   # secondary
    },
    # ── RBI per PA ────────────────────────────────────────────────────────────
    # Power + driving runners in; mirrors HR profile with contact component.
    "RBI_rate": {
        "barrel_pct":          0.28,   # core  — RF #2 (0.099)
        "hard_hit_pct":        0.22,   # core  — RF #3 (0.092)
        "avg_exit_velocity":   0.20,   # core  — RF #1 (0.101)
        "contact_pct":         0.12,   # core  — putting bat on ball
        "fb_pct":              0.08,   # secondary — deep flies score runners
        "pull_pct":            0.06,   # secondary — pull power
        "bb_pct":              0.04,   # secondary — walks can plate runners
    },
    # ── SB per PA ─────────────────────────────────────────────────────────────
    # Sprint speed is decisive; base-reaching ability also matters.
    "SB_rate": {
        "sprint_speed":        0.45,   # core — primary SB predictor (user: core)
        "bb_pct":              0.22,   # core — reaching base is prerequisite
        "contact_pct":         0.15,   # secondary — more contact = more on-base chances
        "o_contact_pct":       0.10,   # secondary — chase contact → fewer Ks, more ABs
        "age":                -0.08,   # secondary (negative) — older → fewer SB
    },
    # ── AVG ───────────────────────────────────────────────────────────────────
    # Two pillars carry equal weight:
    #   A) Contact frequency  — contact_pct, z_contact_pct, k_pct (negative)
    #   B) Contact quality    — avg_exit_velocity, barrel_pct
    #
    # Rationale: elite sluggers (Judge, Ohtani) have exceptional batted-ball
    # quality that offsets strikeout rates; contact specialists (Arraez) have
    # exceptional contact rates that offset poor barrel metrics.  Balancing
    # the two pillars preserves both archetypes.
    #
    # k_pct weight is -0.12 (reduced from -0.25 / -0.18) so K% penalises
    # but does not erase elite quality-of-contact.  Projection is then
    # re-calibrated via _project_avg_calibrated() (see AVG_TARGET_STD above).
    "AVG": {
        # Contact quality (batted-ball)
        "avg_exit_velocity":   0.18,   # core — hard contact falls for hits
                                       #   (reduced slightly so contact specialists
                                       #   like Arraez/Freeman are not undervalued)
        "barrel_pct":          0.18,   # core — elite batted-ball quality (unchanged)
        # Contact frequency / strikeout avoidance
        "contact_pct":         0.24,   # core — overall contact rate (bumped to give
                                       #   contact-specialist archetype more support)
        "z_contact_pct":       0.16,   # core — in-zone contact quality (bumped)
        "k_pct":              -0.12,   # core (light negative) — K% penalises but does
                                       #   not erase elite EV/barrel or contact profiles
        # Secondary
        "ld_pct":              0.06,   # secondary — line drives = highest BABIP
        "sprint_speed":        0.05,   # secondary — beating out grounders
        "gb_pct":             -0.03,   # secondary (negative) — GBs caught more often
        "bb_pct":              0.02,   # secondary — plate discipline / approach proxy
    },
}

# Flat set of all predictor names used across all categories
_ALL_PREDICTOR_COLS: list[str] = sorted({
    feat for weights in PROJECTION_WEIGHTS.values() for feat in weights
})

# ── Projection fingerprint ─────────────────────────────────────────────────────
# A short hash of every config constant that affects the projection output.
# Used as a suffix on the in-memory cache key in main.py so that any change
# to scale factors, weights, stabilization constants, etc. automatically
# invalidates the old cached result and forces a fresh rebuild.
def _build_projection_fingerprint() -> str:
    config = {
        "cache_version":   _CACHE_VERSION,
        "sqrt_r2":         _SQRT_R2,
        "avg_target_std":  AVG_TARGET_STD,
        "scale_factors":   RATE_SCALE_FACTORS,
        "stab_k":          {k: list(v) for k, v in STABILIZATION_K.items()},
        "weights":         {k: sorted(v.items()) for k, v in PROJECTION_WEIGHTS.items()},
    }
    blob = json.dumps(config, sort_keys=True)
    return hashlib.md5(blob.encode()).hexdigest()[:8]


PROJECTION_FINGERPRINT: str = _build_projection_fingerprint()

# FanGraphs column name → snake_case internal name
# Mirrors analysis/feature_builder.py so column coverage stays in sync.
_FG_COL_MAP: dict[str, str] = {
    "BB%":        "bb_pct",
    "K%":         "k_pct",
    "O-Swing%":   "o_swing_pct",
    "Z-Swing%":   "z_swing_pct",
    "Swing%":     "swing_pct",
    "O-Contact%": "o_contact_pct",
    "Z-Contact%": "z_contact_pct",
    "Contact%":   "contact_pct",
    "Whiff%":     "whiff_pct",
    "SwStr%":     "whiff_pct",    # fallback column name
    "HardHit%":   "hard_hit_pct",
    "Hard%":      "hard_hit_pct", # older BIS column name
    "EV":         "avg_exit_velocity",
    "maxEV":      "max_exit_velocity",
    "LA":         "launch_angle_avg",
    "Barrel%":    "barrel_pct",
    "GB%":        "gb_pct",
    "FB%":        "fb_pct",
    "LD%":        "ld_pct",
    "Pull%":      "pull_pct",
    "Cent%":      "cent_pct",
    "Oppo%":      "oppo_pct",
    "Age":        "age",
}


# ── Cache helpers (identical pattern to data_fetcher.py) ─────────────────────

def _cache_path(name: str) -> Path:
    try:
        _cache_dir.mkdir(exist_ok=True)
    except OSError:
        pass  # read-only filesystem (Vercel bundle) — can still read existing files
    return _cache_dir / f"{name}_{_CACHE_VERSION}.parquet"


def _meta_path(name: str) -> Path:
    try:
        _cache_dir.mkdir(exist_ok=True)
    except OSError:
        pass
    return _cache_dir / f"{name}_{_CACHE_VERSION}.meta"


def _is_cache_valid(name: str) -> bool:
    p, m = _cache_path(name), _meta_path(name)
    if not p.exists() or not m.exists():
        return False
    # On Vercel the cache files are from the deployment bundle — always treat as fresh.
    if ON_VERCEL:
        return True
    try:
        ts = datetime.fromisoformat(m.read_text().strip())
        return datetime.utcnow() - ts < timedelta(hours=CACHE_MAX_AGE_HOURS)
    except Exception:
        return False


def _save_cache(name: str, df: pd.DataFrame) -> None:
    try:
        df.to_parquet(_cache_path(name), index=False)
        _meta_path(name).write_text(datetime.utcnow().isoformat())
        logger.info("Cached %s (%d rows)", name, len(df))
    except OSError:
        logger.warning(
            "Could not write projection cache for %s (read-only filesystem — "
            "data will be re-fetched on next cold start)",
            name,
        )


def _load_cache(name: str) -> pd.DataFrame:
    logger.info("Loading %s from disk cache", name)
    return pd.read_parquet(_cache_path(name))


def _retry(fn, retries: int = 3, base_delay: float = 2.0):
    """Call fn(); retry on exception with exponential back-off."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, retries, exc)
            if attempt == retries - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))


# ── Data fetching ─────────────────────────────────────────────────────────────

def _to_pct(s: pd.Series) -> pd.Series:
    """Normalise a percentage column to [0, 1]; FanGraphs is inconsistent."""
    s = pd.to_numeric(s, errors="coerce")
    if s.dropna().mean() > 1.5:
        s = s / 100.0
    return s


def _fetch_sprint_speed_map(season: int) -> dict[int, float]:
    """
    Return a dict mapping FanGraphs IDfg → sprint_speed (ft/sec) for a season.

    Tries Statcast sprint speed leaderboard and joins via the Chadwick register.
    Returns an empty dict on any failure — sprint_speed will remain NaN and be
    imputed to the pool median later.
    """
    if not _HAS_PYBASEBALL:
        logger.warning("pybaseball not installed — sprint speed will be NaN for all players.")
        return {}

    sprint_fn = getattr(pybaseball, "statcast_sprint_speed", None)
    if sprint_fn is None:
        logger.warning("pybaseball.statcast_sprint_speed not available — skipping sprint speed.")
        return {}

    try:
        sp_df: pd.DataFrame = _retry(lambda: sprint_fn(season, min_opp=10))
    except Exception as exc:
        logger.warning("Sprint speed fetch failed for %d: %s", season, exc)
        return {}

    if sp_df is None or sp_df.empty:
        return {}

    spd_col = next((c for c in ["sprint_speed", "r_sprint_speed", "hp_to_1b"] if c in sp_df.columns), None)
    mlbam_col = next((c for c in ["player_id", "batter", "mlbam_id"] if c in sp_df.columns), None)
    if spd_col is None or mlbam_col is None:
        logger.warning("Sprint speed columns not found in response (%s)", list(sp_df.columns))
        return {}

    # Build MLBAM → IDfg map via Chadwick register
    try:
        reg = _retry(lambda: pybaseball.chadwick_register())
        mk = next((c for c in ["key_mlbam", "mlbam_id"] if c in reg.columns), None)
        fk = next((c for c in ["key_fangraphs", "fg_id"] if c in reg.columns), None)
        if mk and fk:
            sub = reg[[mk, fk]].dropna()
            mlbam_to_fg: dict[int, int] = {}
            for _, row in sub.iterrows():
                try:
                    mlbam_to_fg[int(row[mk])] = int(row[fk])
                except (ValueError, TypeError):
                    pass
        else:
            mlbam_to_fg = {}
    except Exception as exc:
        logger.warning("Chadwick register unavailable: %s — sprint speed will be NaN", exc)
        return {}

    result: dict[int, float] = {}
    for _, row in sp_df.iterrows():
        try:
            mlbam_id = int(row[mlbam_col])
            idfg = mlbam_to_fg.get(mlbam_id)
            if idfg is not None:
                spd = pd.to_numeric(row[spd_col], errors="coerce")
                if pd.notna(spd):
                    result[idfg] = float(spd)
        except (ValueError, TypeError):
            pass

    logger.info("Sprint speed map for %d: %d players", season, len(result))
    return result


def _fetch_skill_data(season: int) -> pd.DataFrame:
    """
    Fetch full-season FanGraphs batting stats and extract skill predictors.

    Stores a separate cache from the stripped data in data_fetcher.py so the
    existing rankings workflow is completely unaffected.

    Returns a DataFrame with columns:
        IDfg (int), Name, Team, pa, bbe, + all _ALL_PREDICTOR_COLS

    pa  = plate appearances (sample size for discipline/contact stabilization)
    bbe = batted ball events (FanGraphs "Events"; sample size for power/batted-ball
          stabilization).  NaN for players with zero batted ball events.
    """
    name = f"proj_skill_{season}"
    if _is_cache_valid(name):
        return _load_cache(name)

    if not _HAS_PYBASEBALL:
        raise RuntimeError(
            f"pybaseball is not installed — cannot fetch skill data for {season}. "
            "To refresh, run locally (pip install pybaseball) and commit the updated "
            "parquet files in backend/cache/."
        )

    logger.info("Fetching FanGraphs skill data for %d...", season)
    raw: pd.DataFrame = _retry(lambda: pybaseball.batting_stats(season, qual=1))
    logger.info("  FG %d: %d players, %d columns", season, len(raw), len(raw.columns))

    # Identify the FanGraphs player ID column
    idfg_col = next((c for c in ["IDfg", "playerid", "FG_ID"] if c in raw.columns), None)

    out = pd.DataFrame(index=raw.index)
    out["IDfg"] = pd.to_numeric(raw[idfg_col], errors="coerce") if idfg_col else np.nan
    out["Name"] = raw.get("Name", raw.get("PlayerName", pd.Series("", index=raw.index)))
    out["Team"] = raw.get("Team", pd.Series("", index=raw.index))
    out["pa"]   = pd.to_numeric(raw.get("PA", 0), errors="coerce").fillna(0)
    # BBE (batted ball events) — from FanGraphs "Events" column.
    # Used as the sample-size denominator for batted-ball/power predictor stabilization.
    out["bbe"]  = pd.to_numeric(raw.get("Events", np.nan), errors="coerce").fillna(np.nan)

    # Extract predictor columns — first match wins (Whiff% preferred over SwStr%)
    already_extracted: set[str] = set()
    for fg_col, feat in _FG_COL_MAP.items():
        if fg_col in raw.columns and feat not in already_extracted:
            out[feat] = _to_pct(raw[fg_col])
            already_extracted.add(feat)

    # Ensure every predictor column exists (NaN if not in FG data)
    for feat in _ALL_PREDICTOR_COLS:
        if feat not in out.columns:
            out[feat] = np.nan

    # Supplement sprint_speed from Statcast sprint speed leaderboard
    ss_map = _fetch_sprint_speed_map(season)
    if ss_map:
        out["sprint_speed"] = out["IDfg"].map(ss_map)
    elif "sprint_speed" not in already_extracted:
        out["sprint_speed"] = np.nan

    _save_cache(name, out.reset_index(drop=True))
    logger.info("  Skill data %d: %d players cached", season, len(out))
    return out.reset_index(drop=True)


# ── Projection computation ────────────────────────────────────────────────────

def _stabilize_predictors(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply sample-size stabilization (shrinkage) to each predictor column.

    Formula (James–Stein / reliability-weighted):
        stabilized = (player_stat × n + league_avg × k) / (n + k)

    where:
        n           = observed sample size for this predictor
        league_avg  = cross-sectional mean of the predictor across all players
                      in this season's dataset
        k           = stabilization constant (see STABILIZATION_K)

    Effect:
        • Players with large samples (n >> k) keep their observed values.
        • Players with small samples (n << k) are pulled toward the league mean.
        • k controls the stabilization point: n == k → 50% regression to mean.

    Sample-size source:
        • Discipline/contact stats    → "pa"  (plate appearances)
        • Power/batted-ball stats     → "bbe" (batted ball events, FG "Events")
          If "bbe" column is absent, falls back to "pa" with a warning.

    Not stabilized: "age" (intentional — age is not a rate stat).
    NaN values (player has no data for a predictor) are preserved as NaN.
    """
    df = df.copy()
    bbe_available = "bbe" in df.columns and df["bbe"].notna().any()
    if not bbe_available:
        logger.warning(
            "Stabilization: 'bbe' column not in skill data — "
            "all BBE-based predictors will use 'pa' as fallback. "
            "To get true BBE, clear the proj_v2 cache and re-fetch."
        )

    for feat, (size_col, k) in STABILIZATION_K.items():
        if feat not in df.columns:
            continue  # predictor not present this season — skip silently

        # Determine which sample-size column to use
        actual_size_col = (
            size_col if (size_col == "pa" or bbe_available) else "pa"
        )
        if actual_size_col not in df.columns:
            continue

        n         = pd.to_numeric(df[actual_size_col], errors="coerce").fillna(0)
        v         = pd.to_numeric(df[feat], errors="coerce")
        league_avg = float(v.mean(skipna=True))

        if np.isnan(league_avg):
            continue  # can't compute a league mean — skip

        stabilized = (v * n + league_avg * k) / (n + k)
        # Preserve NaN wherever the player had no observed value
        df[feat] = stabilized.where(v.notna(), other=np.nan)

    return df


def _weighted_merge(
    season_dfs: dict[int, pd.DataFrame],
    base_season: int = 2025,
) -> pd.DataFrame:
    """
    Merge skill DataFrames for each season into one weighted-predictor DataFrame.

    Players are anchored to the base_season pool (must qualify there).
    Prior seasons contribute recency-weighted values for each predictor.

    For players missing data in a prior season, weights are redistributed to
    available seasons so the weighted average is still well-defined.
    """
    base_df = season_dfs[base_season].copy()
    base_df = base_df[base_df["pa"] >= MIN_PA_QUALIFY].reset_index(drop=True)

    # Index base pool by IDfg for fast lookup
    base_idfg = base_df["IDfg"].values

    result = pd.DataFrame()
    result["IDfg"] = base_idfg
    result["Name"] = base_df["Name"].values
    result["Team"] = base_df["Team"].values
    result["pa_2025"] = base_df["pa"].values

    # Pull PA from prior seasons
    for season in PREDICTOR_SEASONS:
        if season == base_season:
            continue
        sdf = season_dfs.get(season, pd.DataFrame())
        if sdf.empty:
            result[f"pa_{season}"] = np.nan
        else:
            pa_map = sdf.dropna(subset=["IDfg"]).set_index("IDfg")["pa"]
            result[f"pa_{season}"] = result["IDfg"].map(pa_map)

    # Compute weighted value for each predictor
    for feat in _ALL_PREDICTOR_COLS:
        weighted_vals = pd.Series(np.nan, index=result.index)

        for i, row_idfg in enumerate(result["IDfg"].values):
            num = 0.0
            denom = 0.0
            for season in PREDICTOR_SEASONS:
                w = SEASON_WEIGHTS[season]
                sdf = season_dfs.get(season, pd.DataFrame())
                if sdf.empty or feat not in sdf.columns:
                    continue
                # Look up this player's value in this season
                match = sdf[sdf["IDfg"] == row_idfg]
                if match.empty:
                    continue
                val = pd.to_numeric(match[feat].iloc[0], errors="coerce")
                if pd.notna(val):
                    num   += w * val
                    denom += w
            if denom > 0:
                weighted_vals.iloc[i] = num / denom

        result[feat] = weighted_vals

    return result


def _zscore(s: pd.Series) -> pd.Series:
    """Sample z-score; returns 0 everywhere if std is 0 or NaN."""
    mean = s.mean()
    std  = s.std(ddof=1)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - mean) / std


def _compute_skill_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Z-score each weighted predictor, then compute one skill score per category.

    Returns df with new columns:  skill_HR_rate, skill_R_rate, skill_RBI_rate,
                                   skill_SB_rate, skill_AVG.
    """
    df = df.copy()

    # Z-score each predictor across the pool
    predictor_z: dict[str, pd.Series] = {}
    for feat in _ALL_PREDICTOR_COLS:
        if feat in df.columns:
            predictor_z[feat] = _zscore(df[feat].fillna(df[feat].median()))
        else:
            predictor_z[feat] = pd.Series(0.0, index=df.index)

    # Category skill score = signed weighted sum of predictor z-scores
    for cat, weights in PROJECTION_WEIGHTS.items():
        score = pd.Series(0.0, index=df.index)
        total_w = sum(abs(w) for w in weights.values())
        for feat, w in weights.items():
            z = predictor_z.get(feat, pd.Series(0.0, index=df.index))
            score += w * z
        if total_w > 0:
            score /= total_w
        df[f"skill_{cat}"] = score

    return df


def _project_rates(
    df: pd.DataFrame,
    rate_col: str,
    actual_vals: pd.Series,
) -> pd.Series:
    """
    Convert a category skill score into a projected rate.

    projected_rate = pool_mean + sqrt(R²) × pool_std × skill_score

    pool_mean and pool_std are computed from the 2025 player pool (actual_vals),
    ensuring the projection is anchored to real-world production levels.
    """
    sqrt_r2   = _SQRT_R2[rate_col]
    skill     = df[f"skill_{rate_col}"]
    pool_mean = float(actual_vals.mean())
    pool_std  = float(actual_vals.std(ddof=1))

    projected = pool_mean + sqrt_r2 * pool_std * skill
    return projected.clip(lower=0.0)


def _project_avg_calibrated(
    df: pd.DataFrame,
    pool_avg_vals: pd.Series,
) -> pd.Series:
    """
    Project AVG using z-score rescaling rather than the sqrt(R²) formula.

    Why a separate path?
        pool_std × sqrt_r2 ≈ 0.034 × 0.50 = 0.017 per skill-score unit.
        Even Arraez (max skill_AVG ≈ 1.5) only projects to pool_mean + 0.026.
        The ceiling ends up at ~0.266, far below realistic elite AVG territory.

    This function instead:
        1. Z-normalises skill_AVG across the player pool → N(0, 1).
        2. Maps those z-scores to a target distribution:
               projected_AVG = pool_mean + AVG_TARGET_STD × skill_z
           where AVG_TARGET_STD = 0.025 is calibrated to produce a realistic
           regression-to-mean spread (actual pool std ≈ 0.034; 25% shrinkage).

    Result:
        Preserves the relative ranking of all players (Arraez-type contact
        specialists still project above average-contact hitters), while
        giving elite hard-contact sluggers like Judge/Ohtani the separation
        they deserve instead of compressing everyone near .240-.266.
    """
    pool_mean  = float(pool_avg_vals.mean())
    skill      = df["skill_AVG"]
    skill_mean = float(skill.mean())
    skill_std  = float(skill.std(ddof=1))

    if skill_std == 0 or np.isnan(skill_std):
        return pd.Series(pool_mean, index=df.index)

    skill_z   = (skill - skill_mean) / skill_std
    projected = pool_mean + AVG_TARGET_STD * skill_z
    # Clip to realistic MLB projection bounds.
    # Floor .200: prevents truly unrealistic projections for marginal players
    #   (e.g. extreme-shift targets or very high-K partial-season qualifiers).
    # Ceiling .320: no projection should exceed a sustained elite-contact level;
    #   Arraez, Betts, and the best modern contact hitters project in the .290-.300
    #   range, so .320 gives a comfortable buffer without going unrealistic.
    return projected.clip(lower=0.200, upper=0.320)


# ── Main entry point ──────────────────────────────────────────────────────────

def build_hitter_projections(limit: int = 500) -> pd.DataFrame:
    """
    Build 2026 hitter projections and return a DataFrame shaped identically to
    the HitterRecord API response:

        rank, Name, Team, AB (= projected_PA), R, HR, RBI, SB, AVG,
        zR, zHR, zRBI, zSB, zAVG, total_z, score_0_100, projected_PA

    The `rank` column is NOT inserted here — the endpoint adds it.

    Process:
        1. Fetch 2023/2024/2025 FG skill data (disk-cached).
        2. Compute recency-weighted predictors for each player.
        3. Z-score predictors vs 2025 pool → category skill scores.
        4. HR/R/RBI/SB: project rates via mean + sqrt(R²) × std × skill.
           AVG: z-score rescaling via _project_avg_calibrated() (wider spread).
        5. Variance scaling: stretch rate distributions via RATE_SCALE_FACTORS
           so counting-stat leaderboards reach realistic MLB totals.
        6. Project PA from recent playing time.
        6. Projected totals = rate × projected_PA.
        7. Fantasy z-scores via the existing compute_hitter_zscores().

    Reusability:
        A future /api/players/grouped?mode=projection endpoint can call this
        function and feed the result into main.py's group_by_team() helper.
    """
    # ── Step 1: Fetch skill data for all predictor seasons ────────────────────
    season_dfs: dict[int, pd.DataFrame] = {}
    for season in PREDICTOR_SEASONS:
        try:
            season_dfs[season] = _fetch_skill_data(season)
        except Exception as exc:
            logger.error("Could not fetch skill data for %d: %s", season, exc)
            season_dfs[season] = pd.DataFrame()

    if season_dfs.get(2025, pd.DataFrame()).empty:
        raise RuntimeError(
            "2025 skill data could not be fetched — projections unavailable."
        )

    # ── Step 1.5: Stabilize predictors toward each season's league average ────
    # Applied before recency weighting so small-sample seasons (injuries, rookies,
    # part-time players) do not receive disproportionate weight.
    # Stabilization constants live in STABILIZATION_K (easy to tune).
    logger.info("Applying per-season predictor stabilization...")
    for season in PREDICTOR_SEASONS:
        sdf = season_dfs.get(season, pd.DataFrame())
        if not sdf.empty:
            season_dfs[season] = _stabilize_predictors(sdf)
    logger.info("  Stabilization complete for %d seasons.", len(PREDICTOR_SEASONS))

    # ── Step 2: Recency-weighted merge ────────────────────────────────────────
    logger.info("Building recency-weighted predictor values (50/30/20)...")
    proj = _weighted_merge(season_dfs, base_season=2025)
    logger.info("  Projection pool: %d players (PA >= %d in 2025)", len(proj), MIN_PA_QUALIFY)

    # ── Step 3: Predictor z-scores → category skill scores ───────────────────
    logger.info("Computing category skill scores...")
    proj = _compute_skill_scores(proj)

    # ── Step 4: Compute pool stats from 2025 actuals for rate anchoring ───────
    # Use the already-fetched 2025 full batting data to get actual rate context
    fg_2025 = season_dfs[2025]
    fg_2025_qual = fg_2025[fg_2025["pa"] >= MIN_PA_QUALIFY].copy()

    # We need actual outcomes (HR, R, RBI, SB, AVG) from the 2025 batting data.
    # These come from the standard data_fetcher which has actual result columns.
    # Fetch 2025 results via the same pybaseball call (already disk-cached by
    # data_fetcher.py, so this is effectively free).
    try:
        import pybaseball as _pb
        actual_2025_raw: pd.DataFrame = _retry(
            lambda: _pb.batting_stats(2025, qual=1)
        )
        idfg_col = next(
            (c for c in ["IDfg", "playerid", "FG_ID"] if c in actual_2025_raw.columns), None
        )
        act = pd.DataFrame()
        act["IDfg"] = (
            pd.to_numeric(actual_2025_raw[idfg_col], errors="coerce")
            if idfg_col else np.nan
        )
        act["pa"]  = pd.to_numeric(actual_2025_raw.get("PA", 0), errors="coerce").fillna(0)
        act["HR"]  = pd.to_numeric(actual_2025_raw.get("HR", 0),  errors="coerce").fillna(0)
        act["R"]   = pd.to_numeric(actual_2025_raw.get("R",  0),  errors="coerce").fillna(0)
        act["RBI"] = pd.to_numeric(actual_2025_raw.get("RBI", 0), errors="coerce").fillna(0)
        act["SB"]  = pd.to_numeric(actual_2025_raw.get("SB", 0),  errors="coerce").fillna(0)
        act["AVG"] = pd.to_numeric(actual_2025_raw.get("AVG", 0), errors="coerce").fillna(0)
        act = act[act["pa"] >= MIN_PA_QUALIFY].reset_index(drop=True)

        # Compute actual rate stats
        act["HR_rate"]  = act["HR"]  / act["pa"].replace(0, np.nan)
        act["R_rate"]   = act["R"]   / act["pa"].replace(0, np.nan)
        act["RBI_rate"] = act["RBI"] / act["pa"].replace(0, np.nan)
        act["SB_rate"]  = act["SB"]  / act["pa"].replace(0, np.nan)
        # AVG is already a rate
        pool_rates = act
    except Exception as exc:
        logger.error("Could not build pool rate stats: %s", exc)
        # Fallback: use reasonable MLB averages if live data unavailable
        pool_rates = pd.DataFrame({
            "HR_rate":  [0.034],
            "R_rate":   [0.100],
            "RBI_rate": [0.085],
            "SB_rate":  [0.018],
            "AVG":      [0.248],
        })

    # ── Step 5: Project rates ─────────────────────────────────────────────────
    logger.info("Projecting rates...")
    for rate_cat in ["HR_rate", "R_rate", "RBI_rate", "SB_rate"]:
        if rate_cat in pool_rates.columns:
            proj[f"proj_{rate_cat}"] = _project_rates(
                proj, rate_cat, pool_rates[rate_cat].dropna()
            )
        else:
            proj[f"proj_{rate_cat}"] = _SQRT_R2[rate_cat]  # fallback constant

    # AVG uses a dedicated z-score rescaling path to avoid distribution compression.
    # See _project_avg_calibrated() and AVG_TARGET_STD for full rationale.
    if "AVG" in pool_rates.columns:
        proj["proj_AVG"] = _project_avg_calibrated(proj, pool_rates["AVG"].dropna())
    else:
        proj["proj_AVG"] = pool_rates.get("AVG", pd.Series([0.248])).iloc[0]

    # ── Step 5.5: Variance scaling for counting-stat rates ────────────────────
    # Stretches projected-rate distributions so leaderboard totals reach
    # realistic MLB ranges.  Formula:
    #     scaled_rate = league_mean + factor × (projected_rate − league_mean)
    # Player ordering is preserved — only the spread widens.
    # AVG is excluded (handled separately above).
    logger.info("Applying rate variance scaling...")
    for rate_cat, factor in RATE_SCALE_FACTORS.items():
        col = f"proj_{rate_cat}"
        if col not in proj.columns:
            continue
        raw_rates = proj[col]
        league_mean = float(raw_rates.mean())
        scaled = league_mean + factor * (raw_rates - league_mean)
        proj[col] = scaled.clip(lower=0.0)
        logger.debug(
            "  %s: mean=%.4f  pre-scale max=%.4f  post-scale max=%.4f",
            rate_cat, league_mean, float(raw_rates.max()), float(proj[col].max()),
        )

    # ── Step 6: Projected PA ──────────────────────────────────────────────────
    logger.info("Projecting plate appearances...")
    pa_25 = proj["pa_2025"].fillna(0).astype(float)
    pa_24 = proj.get("pa_2024", pd.Series(np.nan, index=proj.index)).fillna(np.nan).astype(float)

    has_24 = pa_24.notna()
    proj["projected_PA"] = np.where(
        has_24,
        0.7 * pa_25 + 0.3 * pa_24,   # both seasons available
        0.85 * pa_25,                  # 2024 missing — slight regression
    ).clip(100, 700)

    # ── Step 7: Projected counting totals ────────────────────────────────────
    logger.info("Computing projected totals...")
    ppa = proj["projected_PA"]
    proj["HR"]  = (proj["proj_HR_rate"]  * ppa).round().clip(lower=0).astype(int)
    proj["R"]   = (proj["proj_R_rate"]   * ppa).round().clip(lower=0).astype(int)
    proj["RBI"] = (proj["proj_RBI_rate"] * ppa).round().clip(lower=0).astype(int)
    proj["SB"]  = (proj["proj_SB_rate"]  * ppa).round().clip(lower=0).astype(int)
    proj["AVG"] = proj["proj_AVG"].clip(lower=0.0, upper=0.400).round(3)

    # ── Step 8: Fantasy z-scores ──────────────────────────────────────────────
    # Pass AB = projected_PA so the contribution-based AVG z-score uses PA
    # as the playing-time weight (identical logic to actual rankings).
    logger.info("Computing projected fantasy z-scores...")
    zscore_input = pd.DataFrame({
        "Name": proj["Name"],
        "Team": proj["Team"],
        "AB":   proj["projected_PA"].round().astype(int),
        "R":    proj["R"],
        "HR":   proj["HR"],
        "RBI":  proj["RBI"],
        "SB":   proj["SB"],
        "AVG":  proj["AVG"],
    })

    scored = compute_hitter_zscores(zscore_input)

    # Attach extra fields the endpoint / frontend needs
    scored["projected_PA"] = proj["projected_PA"].round().astype(int).values

    # Sort by total_z descending and take top `limit`
    scored = (
        scored.sort_values("total_z", ascending=False)
        .head(limit)
        .reset_index(drop=True)
    )

    logger.info(
        "Projections complete: %d players | "
        "avg HR=%.1f, R=%.1f, RBI=%.1f, SB=%.1f, AVG=%.3f",
        len(scored),
        scored["HR"].mean(),
        scored["R"].mean(),
        scored["RBI"].mean(),
        scored["SB"].mean(),
        scored["AVG"].mean(),
    )

    return scored

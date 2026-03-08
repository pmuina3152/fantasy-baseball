"""
Configuration for the MLB hitter modeling pipeline.

Default modeling design: year-over-year prediction.
    Predictors = full-season skill metrics from year N
    Targets    = full-season fantasy production from year N+1

Active season pairs:
    2022 → 2023
    2023 → 2024
    2024 → 2025

All configurable constants live here: season pairs, PA thresholds, predictor
feature lists, excluded outcome stats, target stats, output paths, and modeling
parameters.

NOTE — half-season split design:
    The previous design used first-half predictors → second-half targets within
    the same season.  That approach depended on pybaseball.batting_stats_range()
    (Baseball Reference date-range scraping), which is brittle and throws
    "list index out of range" errors.  The year-over-year design below eliminates
    all BRef date-range calls from the critical path.

    If a half-season split is desired in the future, the recommended approach is
    to derive date-window aggregations from raw Statcast pitch-level data
    (pybaseball.statcast(start_dt, end_dt)) rather than relying on BRef scraping.
"""

from pathlib import Path

# ── Directory layout ───────────────────────────────────────────────────────────
BASE_DIR           = Path(__file__).parent
RESULTS_CSV_DIR    = BASE_DIR / "results" / "csv"
RESULTS_JSON_DIR   = BASE_DIR / "results" / "json"
RESULTS_PLOTS_DIR  = BASE_DIR / "results" / "plots"
DATA_RAW_DIR       = BASE_DIR / "data" / "raw"
DATA_PROCESSED_DIR = BASE_DIR / "data" / "processed"

for _d in (RESULTS_CSV_DIR, RESULTS_JSON_DIR, RESULTS_PLOTS_DIR,
           DATA_RAW_DIR, DATA_PROCESSED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Cache ──────────────────────────────────────────────────────────────────────
CACHE_MAX_AGE_HOURS: int = 48
CACHE_VERSION: str = "v2"  # Bumped from v1; invalidates old half-season cache files

# ── Season pairs ───────────────────────────────────────────────────────────────
# Each dict maps one predictor season to the following target season.
# Add or remove pairs here; dataset_builder.py stacks them automatically.
#
# To add a new season pair when 2026 data becomes available:
#   {"predictor_season": 2025, "target_season": 2026}
SEASON_PAIRS: list[dict] = [
    {"predictor_season": 2022, "target_season": 2023},
    {"predictor_season": 2023, "target_season": 2024},
    {"predictor_season": 2024, "target_season": 2025},
]

# ── Qualifying thresholds ──────────────────────────────────────────────────────
# Minimum plate appearances in the PREDICTOR season to qualify.
# 250 PA ≈ roughly half a full season; ensures stable skill metric estimates.
MIN_PA_PREDICTOR_SEASON: int = 250

# Minimum plate appearances in the TARGET season.
# Filters out players who were injured for most of the target year so their
# near-zero target stats don't introduce noise.  Set to 0 to disable.
MIN_PA_TARGET_SEASON: int = 100

# ── Target variables (next-season outcomes to predict) ────────────────────────
TARGET_STATS: list[str] = ["HR", "R", "RBI", "SB", "AVG"]

# ── Rate targets (PA-normalized — removes playing-time confound) ───────────────
# These isolate pure skill by dividing counting totals by plate appearances.
# The rate models run as a SECOND modeling layer alongside the count models.
#
# API note: could power a /api/analysis/skill-models or /api/player/skill-rates endpoint.
RATE_TARGETS: list[str] = ["HR_rate", "R_rate", "RBI_rate", "SB_rate"]

# ── SB-specific supplemental features ─────────────────────────────────────────
# These predictors are added ONLY to the SB and SB_rate models.
# Rationale: stolen-base success depends not just on speed but also on
# opportunity (reaching base) and team context (run environment).
SB_EXTRA_PREDICTORS: list[str] = [
    "times_on_base_proxy",  # PA × approx_OBP — opportunities to attempt steals
    "team_runs_scored",     # Team R scored in predictor season — run environment
]

# ── Predictor feature names (internal clean names, snake_case) ─────────────────
# Only TRUE process / skill variables — no downstream result or composite stats.
#
# Source legend:
#   [FG]  = FanGraphs full-season via pybaseball.batting_stats()
#           This is now the ONLY date-sensitive source for predictors.
#   [SC]  = Statcast aggregated leaderboard via statcast_batter_exitvelo_barrels()
#   [SP]  = Statcast sprint speed leaderboard via statcast_sprint_speed()
#
# All sources are full-season aggregates for the predictor year; no BRef
# date-range calls are needed.

# A) Plate discipline / swing decisions
PLATE_DISCIPLINE_FEATURES: list[str] = [
    "bb_pct",         # Walk rate          [FG: BB%]
    "k_pct",          # Strikeout rate     [FG: K%]
    "o_swing_pct",    # O-Swing%           [FG]
    "z_swing_pct",    # Z-Swing%           [FG]
    "swing_pct",      # Swing%             [FG]
    "o_contact_pct",  # O-Contact%         [FG]
    "z_contact_pct",  # Z-Contact%         [FG]
    "contact_pct",    # Contact%           [FG]
    "whiff_pct",      # Whiff% (or SwStr%) [FG]
]

# B) Quality of contact
CONTACT_QUALITY_FEATURES: list[str] = [
    "avg_exit_velocity",  # Avg exit velocity mph  [FG / SC]
    "max_exit_velocity",  # Max exit velocity mph  [FG / SC]
    "hard_hit_pct",       # HardHit%               [FG / SC]
    "barrel_pct",         # Barrel%                [FG / SC]
    "sweet_spot_pct",     # Sweet spot % (8–32°)   [SC]
]

# C) Launch / batted-ball profile
BATTED_BALL_FEATURES: list[str] = [
    "launch_angle_avg",  # Avg launch angle  [FG / SC]
    "gb_pct",            # GB%               [FG]
    "fb_pct",            # FB%               [FG]
    "ld_pct",            # LD%               [FG]
    "pull_pct",          # Pull%             [FG]
    "cent_pct",          # Center%           [FG]
    "oppo_pct",          # Oppo%             [FG]
]

# D) Speed / athleticism
SPEED_FEATURES: list[str] = [
    "sprint_speed",  # Sprint speed ft/sec  [SP]
]

# E) Opportunity / context
OPPORTUNITY_FEATURES: list[str] = [
    "pa_predictor_season",  # Plate appearances in predictor season  [FG: PA]
    "age",                  # Player age                             [FG: Age]
]

ALL_PREDICTORS: list[str] = (
    PLATE_DISCIPLINE_FEATURES
    + CONTACT_QUALITY_FEATURES
    + BATTED_BALL_FEATURES
    + SPEED_FEATURES
    + OPPORTUNITY_FEATURES
)

# ── Excluded outcome/result metrics (must never appear as predictors) ──────────
EXCLUDED_FROM_PREDICTORS: frozenset[str] = frozenset({
    "avg", "obp", "slg", "ops",
    "woba", "xba", "xslg", "xwoba",
    "iso", "wrc_plus", "wrc", "wraa", "babip",
    "xobp", "xiso",
    "hr", "r", "rbi", "sb",
    "fip", "era", "whip",
})

# ── Modeling settings ──────────────────────────────────────────────────────────
RANDOM_STATE: int = 42

# Top-N features fed into the interpretable OLS model.
OLS_TOP_N_FEATURES: int = 8

# Fallback CV folds used when fewer than 2 unique season groups exist.
CV_FOLDS: int = 5

# ElasticNet l1_ratio grid
ELASTICNET_L1_RATIOS: list[float] = [0.1, 0.5, 0.7, 0.9, 0.95, 0.99, 1.0]

# Random Forest hyperparameters
RF_N_ESTIMATORS: int = 300
RF_MAX_FEATURES: str = "sqrt"
RF_MIN_SAMPLES_LEAF: int = 5

# Missing-value imputation strategy
IMPUTATION_STRATEGY: str = "median"

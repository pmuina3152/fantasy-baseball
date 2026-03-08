"""
Player skill scoring and breakout candidate detection.

Derives three interpretable skill scores from the trained ElasticNet rate models:

    power_skill_score   — weighted z-score of power/EV metrics
                          weights drawn from HR_rate ElasticNet coefficients
    contact_skill_score — weighted z-score of contact/plate-discipline metrics
                          weights drawn from AVG ElasticNet coefficients
    speed_skill_score   — weighted z-score of speed metrics
                          weights drawn from SB_rate ElasticNet coefficients

Z-scores are computed WITHIN each predictor_season (league-relative), so a score
of +1.5 means the player was 1.5 standard deviations above the league average
in that specific season — not an artifact of year-to-year league changes.

The breakout_score combines all three dimensions into one ranking, giving equal
weight to power, hard contact, max EV, sprint speed, and contact rate.

Outputs:
    results/csv/player_skill_scores.csv
    results/json/player_skill_scores.json
    results/csv/breakout_candidates.csv

API endpoint notes:
    player_skill_scores.json   → GET /api/player/skill-scores?name=...&season=2024
    breakout_candidates.csv    → GET /api/analysis/breakout-candidates?season=2024
"""

import json
import logging

import numpy as np
import pandas as pd

from config import RESULTS_CSV_DIR, RESULTS_JSON_DIR
from utils import clean_for_json

logger = logging.getLogger(__name__)


# ── Feature groupings for each skill dimension ────────────────────────────────

POWER_FEATURES   = ["barrel_pct", "avg_exit_velocity", "max_exit_velocity",
                    "hard_hit_pct", "fb_pct"]
CONTACT_FEATURES = ["contact_pct", "z_contact_pct", "o_contact_pct", "k_pct"]
SPEED_FEATURES   = ["sprint_speed"]

# k_pct should be inverted: lower strikeout rate = better contact skill
_CONTACT_INVERT  = {"k_pct"}


# ── Core helpers ──────────────────────────────────────────────────────────────

def _season_zscore(series: pd.Series, seasons: pd.Series) -> pd.Series:
    """
    Compute a per-player z-score normalised within each predictor_season.

    Returns a Series aligned with `series.index`.  Players whose season group
    has fewer than 3 valid values receive z-score = 0.0.
    """
    out = pd.Series(0.0, index=series.index, dtype=float)
    vals = pd.to_numeric(series, errors="coerce")

    for season in sorted(set(int(s) for s in pd.to_numeric(seasons, errors="coerce").dropna())):
        mask = pd.to_numeric(seasons, errors="coerce") == season
        grp  = vals[mask]
        mu   = grp.mean()
        sigma = grp.std(ddof=1)
        if pd.notna(mu) and pd.notna(sigma) and sigma > 1e-8 and mask.sum() >= 3:
            out[mask] = ((grp - mu) / sigma).fillna(0.0)
        else:
            out[mask] = 0.0

    return out


def _get_enet_weights(
    model_results: dict,
    target: str,
    feature_pool: list[str],
) -> dict:
    """
    Extract |ElasticNet standardised coefficient| for each feature in feature_pool.

    Falls back to equal weights if the target is missing or all coefficients are zero.
    """
    enet     = model_results.get(target, {}).get("elastic_net", {})
    coeff_df = enet.get("coeff_df", pd.DataFrame())

    weights: dict = {}
    if not coeff_df.empty:
        for _, row in coeff_df.iterrows():
            if row["feature"] in feature_pool:
                weights[row["feature"]] = max(float(row["abs_coeff"]), 0.0)

    # Fill missing features with 0 (not selected by ElasticNet)
    for f in feature_pool:
        if f not in weights:
            weights[f] = 0.0

    # Fall back to equal weights when everything is zero (e.g., missing target)
    if sum(weights.values()) == 0:
        equal = 1.0 / max(len(feature_pool), 1)
        weights = {f: equal for f in feature_pool}

    return weights


def _weighted_score(
    df: pd.DataFrame,
    features: list[str],
    weights: dict,
    season_col: str = "predictor_season",
    invert: set | None = None,
) -> pd.Series:
    """
    Compute a normalised weighted sum of per-season z-scores for the given features.

    Args:
        features:   Features to include in the score.
        weights:    Dict mapping feature → weight (unnormalised).
        season_col: Column used to stratify z-score computation.
        invert:     Set of feature names where lower value = better (e.g., k_pct).

    Returns:
        A Series of float scores, one per row in df.
    """
    invert   = invert or set()
    seasons  = df[season_col] if season_col in df.columns else pd.Series(
        [0] * len(df), index=df.index
    )

    score    = pd.Series(0.0, index=df.index)
    total_w  = 0.0

    for feat in features:
        if feat not in df.columns:
            continue
        w = weights.get(feat, 0.0)
        if w <= 0:
            continue

        z = _season_zscore(df[feat], seasons)
        if feat in invert:
            z = -z

        score   += w * z
        total_w += w

    if total_w > 0:
        score /= total_w

    return score.round(4)


# ── Public entry points ───────────────────────────────────────────────────────

def compute_skill_scores(
    modeling_df: pd.DataFrame,
    rate_model_results: dict,
    main_model_results: dict | None = None,
) -> pd.DataFrame:
    """
    Compute power_skill_score, contact_skill_score, speed_skill_score for every
    player-season row in the modeling dataset.

    Weight sources:
        power   ← HR_rate ElasticNet abs coefficients
        contact ← AVG ElasticNet abs coefficients (AVG is itself a rate stat)
        speed   ← SB_rate ElasticNet abs coefficients

    Z-scores are league-relative within each predictor_season.

    Args:
        modeling_df:        Full modeling dataset (output of build_modeling_dataset).
        rate_model_results: Output of run_rate_models().
        main_model_results: Output of run_all_models().  Used for AVG contact weights.

    Returns:
        modeling_df with three new columns appended.
    """
    df = modeling_df.copy()

    power_weights = _get_enet_weights(rate_model_results, "HR_rate",  POWER_FEATURES)

    # AVG is a rate stat by nature — use the main model's AVG coefficients for
    # contact weights when available; fall back to rate models otherwise
    contact_source = main_model_results if main_model_results else rate_model_results
    contact_weights = _get_enet_weights(contact_source, "AVG", CONTACT_FEATURES)

    speed_weights = _get_enet_weights(rate_model_results, "SB_rate", SPEED_FEATURES)

    logger.info(
        "Skill score weights — power (HR_rate): %s",
        {k: round(v, 3) for k, v in power_weights.items() if v > 0},
    )
    logger.info(
        "Skill score weights — contact (AVG):   %s",
        {k: round(v, 3) for k, v in contact_weights.items() if v > 0},
    )
    logger.info(
        "Skill score weights — speed (SB_rate): %s",
        {k: round(v, 3) for k, v in speed_weights.items() if v > 0},
    )

    df["power_skill_score"] = _weighted_score(
        df, POWER_FEATURES, power_weights
    )
    df["contact_skill_score"] = _weighted_score(
        df, CONTACT_FEATURES, contact_weights, invert=_CONTACT_INVERT
    )
    df["speed_skill_score"] = _weighted_score(
        df, SPEED_FEATURES, speed_weights
    )

    logger.info(
        "Skill scores computed for %d players "
        "(power mean=%.3f, contact mean=%.3f, speed mean=%.3f)",
        len(df),
        df["power_skill_score"].mean(),
        df["contact_skill_score"].mean(),
        df["speed_skill_score"].mean(),
    )

    return df


def compute_breakout_candidates(df_with_scores: pd.DataFrame) -> pd.DataFrame:
    """
    Rank players by a combined breakout_score.

    breakout_score = equal-weight z-score composite of:
        Barrel%  (power ceiling)
        HardHit% (contact quality)
        MaxEV    (raw power)
        SprintSpeed (athleticism)
        Contact% (bat-to-ball skill)

    Equal weights are used deliberately so no single dimension dominates.
    Players are sorted descending by breakout_score within each predictor_season.

    Returns:
        DataFrame with columns:
            player_name, predictor_season, team_fg,
            power_skill_score, contact_skill_score, speed_skill_score,
            breakout_score
    """
    breakout_features = [
        "barrel_pct", "hard_hit_pct", "max_exit_velocity",
        "sprint_speed", "contact_pct",
    ]
    equal_weights = {f: 1.0 for f in breakout_features}

    df = df_with_scores.copy()
    df["breakout_score"] = _weighted_score(
        df, breakout_features, equal_weights
    )

    id_cols = ["name_raw_fg", "predictor_season", "team_fg"]
    score_cols = ["power_skill_score", "contact_skill_score",
                  "speed_skill_score", "breakout_score"]

    keep = [c for c in id_cols + score_cols if c in df.columns]
    out = (
        df[keep]
        .rename(columns={"name_raw_fg": "player_name"})
        .sort_values("breakout_score", ascending=False)
        .reset_index(drop=True)
    )
    return out


# ── Save helpers ──────────────────────────────────────────────────────────────

def save_skill_scores(df_with_scores: pd.DataFrame) -> None:
    """
    Save player_skill_scores.csv and player_skill_scores.json.

    Output:
        results/csv/player_skill_scores.csv
        results/json/player_skill_scores.json

    API endpoint note:
        player_skill_scores.json could feed:
            GET /api/player/skill-scores?name=Aaron+Judge&season=2024
        or a player card endpoint that shows power/contact/speed gauges.
    """
    id_cols    = ["name_raw_fg", "fg_id", "predictor_season",
                  "target_season", "team_fg"]
    score_cols = ["power_skill_score", "contact_skill_score", "speed_skill_score"]

    keep = [c for c in id_cols + score_cols if c in df_with_scores.columns]
    out  = df_with_scores[keep].rename(columns={"name_raw_fg": "player_name"}).copy()

    csv_path = RESULTS_CSV_DIR / "player_skill_scores.csv"
    out.to_csv(csv_path, index=False)
    logger.info("Saved player skill scores CSV -> %s  (%d records)", csv_path, len(out))

    # Serialise fg_id to plain int for JSON (Int64 is not JSON-serialisable)
    json_df = out.copy()
    if "fg_id" in json_df.columns:
        json_df["fg_id"] = json_df["fg_id"].apply(
            lambda x: int(x) if pd.notna(x) else None
        )

    records  = clean_for_json(json_df.to_dict(orient="records"))
    json_path = RESULTS_JSON_DIR / "player_skill_scores.json"
    with open(json_path, "w") as f:
        json.dump(records, f, indent=2)
    logger.info("Saved player skill scores JSON -> %s", json_path)


def save_breakout_candidates(breakout_df: pd.DataFrame) -> None:
    """
    Save breakout_candidates.csv sorted descending by breakout_score.

    Output: results/csv/breakout_candidates.csv

    Columns: player_name, predictor_season, [team_fg],
             power_skill_score, contact_skill_score, speed_skill_score,
             breakout_score

    API endpoint note:
        GET /api/analysis/breakout-candidates?season=2024&top_n=30
    """
    for col in ["power_skill_score", "contact_skill_score",
                "speed_skill_score", "breakout_score"]:
        if col in breakout_df.columns:
            breakout_df[col] = breakout_df[col].round(4)

    path = RESULTS_CSV_DIR / "breakout_candidates.csv"
    breakout_df.to_csv(path, index=False)
    logger.info(
        "Saved breakout candidates -> %s  (%d records)", path, len(breakout_df)
    )

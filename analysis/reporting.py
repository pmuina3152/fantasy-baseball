"""
Save model results to CSV, JSON, and optional plots.

All outputs land in the directories declared in config.py:
    results/csv/   — tabular summaries for spreadsheet / pandas consumption
    results/json/  — machine-readable summaries for website / API integration
    results/plots/ — feature importance bar charts (optional, requires matplotlib)

CSV outputs:
    model_performance_summary.csv     — CV-R² per model per target
    elastic_net_features.csv          — ElasticNet selected features per target
    random_forest_importances.csv     — RF feature importances per target
    ols_coefficients.csv              — OLS coefficients / p-values per target

JSON outputs:
    target_feature_rankings.json      — website-ready per-target feature rankings
    model_summary.json                — top-level model performance summary
    player_profiles.json              — per-player feature + next-season actuals
                                        (shaped for frontend player insight cards)

API endpoint note:
    Each save_*() function mirrors what a future backend endpoint would return.
    For example, save_target_feature_rankings() could feed:
        GET /api/analysis/feature-rankings?target=HR
    And player_profiles.json could feed:
        GET /api/analysis/player-profile?name=Aaron+Judge&season=2024
"""

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    ALL_PREDICTORS,
    RESULTS_CSV_DIR,
    RESULTS_JSON_DIR,
    RESULTS_PLOTS_DIR,
    TARGET_STATS,
)
from utils import clean_for_json

logger = logging.getLogger(__name__)


# ── CSV helpers ───────────────────────────────────────────────────────────────

def save_model_performance_summary(
    model_results: dict,
    filename: str = "model_performance_summary.csv",
) -> pd.DataFrame:
    """
    Save a table of cross-validated R² ± std for each (target, model) pair.

    CV-R² for ElasticNet and RF is leave-one-season-out (GroupKFold).
    OLS R² is the in-sample fit on the full dataset (no CV).

    Args:
        filename: Output filename within results/csv/.  Override to
                  "rate_model_performance_summary.csv" for rate model results.

    Output: results/csv/{filename}
    """
    rows = []
    for target, res in model_results.items():
        for model_key, label in [
            ("elastic_net",   "ElasticNetCV"),
            ("random_forest", "RandomForestRegressor"),
        ]:
            mres = res.get(model_key, {})
            rows.append({
                "target":         target,
                "model":          label,
                "cv_r2_mean":     round(mres.get("cv_r2_mean", np.nan), 4),
                "cv_r2_std":      round(mres.get("cv_r2_std",  np.nan), 4),
                "n_samples":      res.get("n_samples", np.nan),
                "n_season_pairs": res.get("n_season_pairs", np.nan),
            })

        ols = res.get("ols", {})
        rows.append({
            "target":         target,
            "model":          "OLS",
            "cv_r2_mean":     round(ols.get("r2",     np.nan), 4),
            "cv_r2_std":      np.nan,  # OLS fit on full data, not CV
            "n_samples":      ols.get("n_obs", np.nan),
            "n_season_pairs": res.get("n_season_pairs", np.nan),
        })

    df = pd.DataFrame(rows)
    path = RESULTS_CSV_DIR / filename
    df.to_csv(path, index=False)
    logger.info("Saved model performance summary -> %s", path)
    return df


def save_elastic_net_features(
    model_results: dict,
    filename: str = "elastic_net_features.csv",
) -> pd.DataFrame:
    """
    Save ElasticNet-selected features and standardised coefficients per target.

    Args:
        filename: Output filename within results/csv/.  Override to
                  "rate_elastic_net_features.csv" for rate model results.

    Output: results/csv/{filename}
    """
    rows = []
    for target, res in model_results.items():
        enet     = res.get("elastic_net", {})
        coeff_df = enet.get("coeff_df", pd.DataFrame())
        if coeff_df.empty:
            continue
        for _, row in coeff_df.iterrows():
            rows.append({
                "target":    target,
                "feature":   row["feature"],
                "std_coeff": round(row["std_coeff"], 6),
                "abs_coeff": round(row["abs_coeff"], 6),
                "selected":  row["abs_coeff"] > 0,
                "cv_r2":     round(enet.get("cv_r2_mean", np.nan), 4),
            })

    df = pd.DataFrame(rows)
    path = RESULTS_CSV_DIR / filename
    df.to_csv(path, index=False)
    logger.info("Saved ElasticNet features -> %s", path)
    return df


def save_rf_importances(
    model_results: dict,
    filename: str = "random_forest_importances.csv",
) -> pd.DataFrame:
    """
    Save Random Forest feature importances per target.

    Args:
        filename: Output filename within results/csv/.  Override to
                  "rate_random_forest_importances.csv" for rate model results.

    Output: results/csv/{filename}
    """
    rows = []
    for target, res in model_results.items():
        rf     = res.get("random_forest", {})
        imp_df = rf.get("importance_df", pd.DataFrame())
        if imp_df.empty:
            continue
        for rank, (_, row) in enumerate(imp_df.iterrows(), start=1):
            rows.append({
                "target":     target,
                "rank":       rank,
                "feature":    row["feature"],
                "importance": round(row["importance"], 6),
                "cv_r2":      round(rf.get("cv_r2_mean", np.nan), 4),
            })

    df = pd.DataFrame(rows)
    path = RESULTS_CSV_DIR / filename
    df.to_csv(path, index=False)
    logger.info("Saved RF importances -> %s", path)
    return df


def save_ols_coefficients(model_results: dict) -> pd.DataFrame:
    """
    Save OLS coefficients, p-values, and fit stats per target.

    NOTE: OLS is fit on the full stacked dataset (not CV).  With three
    season pairs and ~450–600 observations the p-values are meaningful,
    but treat them as suggestive given the small-to-medium sample size.

    Output: results/csv/ols_coefficients.csv
    """
    rows = []
    for target, res in model_results.items():
        ols      = res.get("ols", {})
        coeff_df = ols.get("coeff_df", pd.DataFrame())
        if coeff_df.empty:
            continue
        for _, row in coeff_df.iterrows():
            rows.append({
                "target":        target,
                "feature":       row["feature"],
                "coeff":         round(row["coeff"],         6),
                "std_err":       round(row["std_err"],        6),
                "t_stat":        round(row["t_stat"],         4),
                "p_value":       round(row["p_value"],        6),
                "conf_int_low":  round(row["conf_int_low"],   6),
                "conf_int_high": round(row["conf_int_high"],  6),
                "model_r2":      round(ols.get("r2",     np.nan), 4),
                "model_adj_r2":  round(ols.get("adj_r2", np.nan), 4),
                "n_obs":         ols.get("n_obs", np.nan),
            })

    df = pd.DataFrame(rows)
    path = RESULTS_CSV_DIR / "ols_coefficients.csv"
    df.to_csv(path, index=False)
    logger.info("Saved OLS coefficients → %s", path)
    return df


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _build_target_feature_rankings(model_results: dict) -> dict:
    """
    Build a website-friendly dict of top predictors per target.

    Shape:
    {
      "HR": {
        "top_predictors": [
          {
            "rank": 1,
            "feature": "barrel_pct",
            "label": "Barrel Rate",
            "rf_importance": 0.234,
            "enet_std_coeff": 0.67,
            "ols_coeff": 0.48,
            "ols_p_value": 0.003,
            "ols_significant": true,
            "enet_selected": true
          }, ...
        ],
        "model_cv_r2": {"elastic_net": 0.45, "random_forest": 0.52},
        "cv_type": "leave-one-season-out",
        "ols_r2": 0.38,
        "n_samples": 480,
        "n_season_pairs": 3
      }, ...
    }
    """
    _FEATURE_LABELS = {
        "bb_pct":              "Walk Rate (BB%)",
        "k_pct":               "Strikeout Rate (K%)",
        "o_swing_pct":         "Chase Rate (O-Swing%)",
        "z_swing_pct":         "Zone Swing Rate (Z-Swing%)",
        "swing_pct":           "Overall Swing Rate",
        "o_contact_pct":       "Outside Contact Rate",
        "z_contact_pct":       "Zone Contact Rate",
        "contact_pct":         "Overall Contact Rate",
        "whiff_pct":           "Whiff Rate",
        "avg_exit_velocity":   "Average Exit Velocity",
        "max_exit_velocity":   "Max Exit Velocity",
        "hard_hit_pct":        "Hard Hit Rate",
        "barrel_pct":          "Barrel Rate",
        "sweet_spot_pct":      "Sweet Spot Rate",
        "launch_angle_avg":    "Average Launch Angle",
        "gb_pct":              "Ground Ball Rate",
        "fb_pct":              "Fly Ball Rate",
        "ld_pct":              "Line Drive Rate",
        "pull_pct":            "Pull Rate",
        "cent_pct":            "Center Rate",
        "oppo_pct":            "Opposite Field Rate",
        "sprint_speed":        "Sprint Speed (ft/sec)",
        "pa_predictor_season": "Plate Appearances (Predictor Season)",
        "age":                 "Age",
    }

    output: dict = {}

    for target, res in model_results.items():
        enet = res.get("elastic_net",   {})
        rf   = res.get("random_forest", {})
        ols  = res.get("ols",           {})

        enet_coeff_map = {}
        for _, row in enet.get("coeff_df", pd.DataFrame()).iterrows():
            enet_coeff_map[row["feature"]] = row["std_coeff"]

        rf_imp_map = {}
        for _, row in rf.get("importance_df", pd.DataFrame()).iterrows():
            rf_imp_map[row["feature"]] = row["importance"]

        ols_coeff_map  = {}
        ols_pvalue_map = {}
        for _, row in ols.get("coeff_df", pd.DataFrame()).iterrows():
            if row["feature"] != "const":
                ols_coeff_map[row["feature"]]  = row["coeff"]
                ols_pvalue_map[row["feature"]] = row["p_value"]

        all_features = res.get("feature_names", list(rf_imp_map.keys()))
        ranked = sorted(all_features, key=lambda f: rf_imp_map.get(f, 0), reverse=True)

        top_predictors = []
        for rank, feat in enumerate(ranked, start=1):
            p_val = ols_pvalue_map.get(feat)
            top_predictors.append({
                "rank":           rank,
                "feature":        feat,
                "label":          _FEATURE_LABELS.get(feat, feat),
                "rf_importance":  round(rf_imp_map.get(feat, 0.0), 6),
                "enet_std_coeff": round(enet_coeff_map.get(feat, 0.0), 6),
                "ols_coeff":      round(ols_coeff_map[feat], 6) if feat in ols_coeff_map else None,
                "ols_p_value":    round(p_val, 4) if p_val is not None else None,
                "ols_significant": (p_val < 0.05) if p_val is not None else None,
                "enet_selected":  enet_coeff_map.get(feat, 0.0) != 0.0,
            })

        n_pairs = res.get("n_season_pairs", 0)
        output[target] = {
            "top_predictors": top_predictors,
            "model_cv_r2": {
                "elastic_net":   round(enet.get("cv_r2_mean", np.nan), 4),
                "random_forest": round(rf.get("cv_r2_mean",  np.nan), 4),
            },
            "cv_type":       "leave-one-season-out" if n_pairs >= 2 else "k-fold",
            "ols_r2":        round(ols.get("r2",     np.nan), 4),
            "ols_adj_r2":    round(ols.get("adj_r2", np.nan), 4),
            "n_samples":     res.get("n_samples", 0),
            "n_season_pairs": n_pairs,
        }

    return output


def save_target_feature_rankings(model_results: dict) -> dict:
    """
    Save per-target feature rankings as a website-ready JSON.

    Output: results/json/target_feature_rankings.json
    """
    data = _build_target_feature_rankings(model_results)
    path = RESULTS_JSON_DIR / "target_feature_rankings.json"
    with open(path, "w") as f:
        json.dump(clean_for_json(data), f, indent=2)
    logger.info("Saved target feature rankings → %s", path)
    return data


def save_model_summary_json(model_results: dict) -> dict:
    """
    Save a concise top-level model summary JSON.

    Output: results/json/model_summary.json

    Shape:
    {
      "generated_at": "...",
      "modeling_design": "year-over-year",
      "season_pairs": [...],
      "targets": ["HR", "R", "RBI", "SB", "AVG"],
      "cv_type": "leave-one-season-out (GroupKFold)",
      "model_performance": { "HR": {...}, ... },
      "top_3_predictors_by_target": { "HR": [...], ... }
    }
    """
    from datetime import datetime
    from config import SEASON_PAIRS

    performance: dict = {}
    top3: dict = {}

    for target, res in model_results.items():
        enet = res.get("elastic_net",   {})
        rf   = res.get("random_forest", {})
        ols  = res.get("ols",           {})

        performance[target] = {
            "elastic_net_cv_r2":     round(enet.get("cv_r2_mean", np.nan), 4),
            "elastic_net_cv_r2_std": round(enet.get("cv_r2_std",  np.nan), 4),
            "rf_cv_r2":              round(rf.get("cv_r2_mean",   np.nan), 4),
            "rf_cv_r2_std":          round(rf.get("cv_r2_std",    np.nan), 4),
            "ols_r2":                round(ols.get("r2",          np.nan), 4),
            "ols_adj_r2":            round(ols.get("adj_r2",      np.nan), 4),
            "n_samples":             res.get("n_samples", 0),
            "n_season_pairs":        res.get("n_season_pairs", 0),
        }

        imp_df = rf.get("importance_df", pd.DataFrame())
        top3[target] = imp_df["feature"].head(3).tolist() if not imp_df.empty else []

    summary = {
        "generated_at":    datetime.utcnow().isoformat() + "Z",
        "modeling_design": "year-over-year (season N predictors → season N+1 targets)",
        "season_pairs":    [
            f"{p['predictor_season']} → {p['target_season']}" for p in SEASON_PAIRS
        ],
        "targets":         TARGET_STATS,
        "cv_type":         "leave-one-season-out (GroupKFold by predictor_season)",
        "model_performance":            performance,
        "top_3_predictors_by_target":   top3,
        "note": (
            "CV-R² values are leave-one-season-out: train on N-1 season pairs, "
            "test on the held-out pair.  This is a genuine out-of-sample estimate."
        ),
    }

    path = RESULTS_JSON_DIR / "model_summary.json"
    with open(path, "w") as f:
        json.dump(clean_for_json(summary), f, indent=2)
    logger.info("Saved model summary JSON → %s", path)
    return summary


def save_player_profiles_json(df: pd.DataFrame) -> list[dict]:
    """
    Save a player-level JSON shaped for frontend player insight cards.

    Each entry contains a player's predictor-season skill profile and their
    actual next-season production.

    Output: results/json/player_profiles.json

    Frontend card shape:
    {
      "name":            "Aaron Judge",
      "predictor_season": 2024,
      "target_season":    2025,
      "team":            "NYY",
      "pa_predictor_season": 567,
      "features": {
        "barrel_pct": 0.187,
        "avg_exit_velocity": 96.1,
        ...
      },
      "next_season": {
        "HR": 58, "R": 122, "RBI": 144, "SB": 10, "AVG": 0.322
      },
      "next_pa": 697
    }
    """
    profiles = []
    target_col_map = {f"next_{s}": s for s in TARGET_STATS}
    feat_cols = [
        c for c in ALL_PREDICTORS
        if c in df.columns and c != "pa_predictor_season"
    ]

    for _, row in df.iterrows():
        features = {
            col: (None if pd.isna(row[col]) else round(float(row[col]), 4))
            for col in feat_cols
            if col in row.index
        }

        next_season: dict = {}
        for col, stat in target_col_map.items():
            if col not in row.index:
                continue
            val = row[col]
            if stat == "AVG":
                next_season[stat] = round(float(val), 4) if pd.notna(val) else None
            else:
                next_season[stat] = int(val) if pd.notna(val) else None

        profiles.append({
            "name":             str(row.get("name_raw_fg", row.get("norm_name", ""))),
            "predictor_season": int(row["predictor_season"]) if pd.notna(row.get("predictor_season")) else None,
            "target_season":    int(row["target_season"])    if pd.notna(row.get("target_season"))    else None,
            "team":             str(row.get("team_fg", "")),
            "pa_predictor_season": int(row["pa_predictor_season"]) if pd.notna(row.get("pa_predictor_season")) else None,
            "features":    features,
            "next_season": next_season,
            "next_pa":     int(row["next_PA"]) if "next_PA" in row.index and pd.notna(row.get("next_PA")) else None,
        })

    path = RESULTS_JSON_DIR / "player_profiles.json"
    with open(path, "w") as f:
        json.dump(clean_for_json(profiles), f, indent=2)
    logger.info("Saved player profiles JSON → %s  (%d records)", path, len(profiles))
    return profiles


# ── Website feature drivers JSON (PART 4 extension) ──────────────────────────

def save_website_feature_drivers(
    model_results: dict,
    rate_model_results: Optional[dict] = None,
    top_n: int = 8,
) -> dict:
    """
    Save a lightweight JSON shaped for direct frontend consumption.

    Structure per target:
    {
      "HR": {
        "top_predictors": [
          {"stat": "barrel_pct", "label": "Barrel Rate", "importance": 0.23,
           "enet_coeff": 0.67, "is_rate_model": false},
          ...
        ],
        "model_cv_r2": 0.45,
        "model_type": "count"   // or "rate"
      },
      "HR_rate": { ... }
    }

    Combines RF importance (primary ranking) with ElasticNet coefficient direction
    so the frontend can show arrows (positive/negative influence) alongside bars.

    Output: results/json/website_feature_drivers.json

    API endpoint note:
        GET /api/analysis/feature-drivers?target=HR  →  this file, filtered by target.
        Could power a "Key metrics that drive HR production" panel on player cards.
    """
    _FEATURE_LABELS = {
        "bb_pct":              "Walk Rate (BB%)",
        "k_pct":               "Strikeout Rate (K%)",
        "o_swing_pct":         "Chase Rate (O-Swing%)",
        "z_swing_pct":         "Zone Swing Rate",
        "swing_pct":           "Overall Swing Rate",
        "o_contact_pct":       "Outside Contact Rate",
        "z_contact_pct":       "Zone Contact Rate",
        "contact_pct":         "Overall Contact Rate",
        "whiff_pct":           "Whiff Rate",
        "avg_exit_velocity":   "Avg Exit Velocity",
        "max_exit_velocity":   "Max Exit Velocity",
        "hard_hit_pct":        "Hard Hit Rate",
        "barrel_pct":          "Barrel Rate",
        "sweet_spot_pct":      "Sweet Spot Rate",
        "launch_angle_avg":    "Avg Launch Angle",
        "gb_pct":              "Ground Ball Rate",
        "fb_pct":              "Fly Ball Rate",
        "ld_pct":              "Line Drive Rate",
        "pull_pct":            "Pull Rate",
        "cent_pct":            "Center Rate",
        "oppo_pct":            "Opposite Field Rate",
        "sprint_speed":        "Sprint Speed (ft/s)",
        "pa_predictor_season": "Plate Appearances",
        "age":                 "Age",
        "times_on_base_proxy": "Times on Base (proxy)",
        "team_runs_scored":    "Team Runs Scored",
    }

    output: dict = {}

    all_results = list(model_results.items())
    if rate_model_results:
        all_results += list(rate_model_results.items())

    for target, res in all_results:
        rf   = res.get("random_forest", {})
        enet = res.get("elastic_net",   {})

        imp_df = rf.get("importance_df", pd.DataFrame())
        if imp_df.empty:
            continue

        enet_coeff_map: dict = {}
        for _, row in enet.get("coeff_df", pd.DataFrame()).iterrows():
            enet_coeff_map[row["feature"]] = float(row["std_coeff"])

        top = imp_df.head(top_n)
        top_predictors = []
        for _, row in top.iterrows():
            feat = row["feature"]
            coeff = enet_coeff_map.get(feat, 0.0)
            top_predictors.append({
                "stat":       feat,
                "label":      _FEATURE_LABELS.get(feat, feat),
                "importance": round(float(row["importance"]), 4),
                "enet_coeff": round(coeff, 4),
                "direction":  "positive" if coeff >= 0 else "negative",
            })

        is_rate = target in (rate_model_results or {})
        output[target] = {
            "top_predictors": top_predictors,
            "model_cv_r2":    round(rf.get("cv_r2_mean", np.nan), 4),
            "model_type":     "rate" if is_rate else "count",
        }

    path = RESULTS_JSON_DIR / "website_feature_drivers.json"
    with open(path, "w") as f:
        json.dump(clean_for_json(output), f, indent=2)
    logger.info("Saved website feature drivers -> %s  (%d targets)", path, len(output))
    return output


# ── Plots ─────────────────────────────────────────────────────────────────────

def save_importance_plots(model_results: dict, top_n: int = 12) -> None:
    """
    Save feature importance bar charts for each target variable.

    Left panel:  RF importance (mean decrease impurity)
    Right panel: |ElasticNet standardised coefficient|

    Output: results/plots/importance_<TARGET>.png

    Silently skips if matplotlib is not installed.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not installed — skipping importance plots.")
        return

    for target, res in model_results.items():
        rf   = res.get("random_forest", {})
        enet = res.get("elastic_net",   {})

        rf_df  = rf.get("importance_df",   pd.DataFrame()).head(top_n)
        en_df  = enet.get("coeff_df",      pd.DataFrame())
        en_sel = en_df[en_df["abs_coeff"] > 0].head(top_n)

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(
            f"Top Predictors of Next-Season {target}",
            fontsize=14, fontweight="bold",
        )

        if not rf_df.empty:
            ax = axes[0]
            ax.barh(rf_df["feature"][::-1], rf_df["importance"][::-1], color="#4C9BE8")
            ax.set_title("Random Forest Importance\n(leave-one-season-out CV)")
            ax.set_xlabel("Mean Decrease Impurity")
            ax.tick_params(axis="y", labelsize=9)

        if not en_sel.empty:
            ax = axes[1]
            colors = [
                "#E84C4C" if c < 0 else "#4CE87A"
                for c in en_sel["std_coeff"][::-1]
            ]
            ax.barh(en_sel["feature"][::-1], en_sel["abs_coeff"][::-1], color=colors)
            ax.set_title("ElasticNet |Std Coefficient|\n(green = positive, red = negative)")
            ax.set_xlabel("|Standardised Coefficient|")
            ax.tick_params(axis="y", labelsize=9)

        plt.tight_layout()
        out_path = RESULTS_PLOTS_DIR / f"importance_{target}.png"
        plt.savefig(out_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved importance plot → %s", out_path)


# ── Master save ───────────────────────────────────────────────────────────────

def save_all_results(
    model_results: dict,
    modeling_df: pd.DataFrame,
    rate_model_results: Optional[dict] = None,
    skill_scores_df: Optional[pd.DataFrame] = None,
    breakout_df: Optional[pd.DataFrame] = None,
    plots: bool = True,
) -> None:
    """
    Run all save functions in one call.  Entry point from run_hitter_pipeline.py.

    Args:
        model_results:      Results from run_all_models() (count targets).
        modeling_df:        Full modeling dataset.
        rate_model_results: Results from run_rate_models() (rate targets).  Optional.
        skill_scores_df:    DataFrame with power/contact/speed skill scores.  Optional.
        breakout_df:        DataFrame with breakout candidates.  Optional.
        plots:              Whether to generate importance plots.
    """
    from skill_scores import save_skill_scores, save_breakout_candidates

    logger.info("Saving all results...")

    # Main count-target model outputs (unchanged)
    save_model_performance_summary(model_results)
    save_elastic_net_features(model_results)
    save_rf_importances(model_results)
    save_ols_coefficients(model_results)
    save_target_feature_rankings(model_results)
    save_model_summary_json(model_results)
    save_player_profiles_json(modeling_df)

    # Rate-target model outputs (PART 1)
    if rate_model_results:
        save_model_performance_summary(
            rate_model_results, filename="rate_model_performance_summary.csv"
        )
        save_elastic_net_features(
            rate_model_results, filename="rate_elastic_net_features.csv"
        )
        save_rf_importances(
            rate_model_results, filename="rate_random_forest_importances.csv"
        )

    # Website feature drivers JSON (PART 4)
    save_website_feature_drivers(model_results, rate_model_results)

    # Skill scores and breakout candidates (PARTS 2 & 5)
    if skill_scores_df is not None:
        save_skill_scores(skill_scores_df)
    if breakout_df is not None:
        save_breakout_candidates(breakout_df)

    if plots:
        save_importance_plots(model_results)

    logger.info("All results saved.")
    logger.info("  CSV  -> %s", RESULTS_CSV_DIR)
    logger.info("  JSON -> %s", RESULTS_JSON_DIR)
    logger.info("  Plots-> %s", RESULTS_PLOTS_DIR)

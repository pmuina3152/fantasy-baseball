"""
run_hitter_pipeline.py — Single-command entry point for the MLB hitter modeling pipeline.

Modeling design: year-over-year prediction
    Predictor features = full-season skill metrics from year N  (FanGraphs + Statcast)
    Target variables   = full-season fantasy production from year N+1 (FanGraphs)
    Active pairs:      2022→2023,  2023→2024,  2024→2025

Usage:
    cd fantasy-baseball/analysis
    python run_hitter_pipeline.py

Options:
    --skip-data    Load previously saved dataset instead of re-fetching
    --no-plots     Skip matplotlib importance plots
    --pairs        Comma-separated predictor seasons to include
                   e.g. --pairs 2022,2023,2024  (default: all in config.SEASON_PAIRS)

What it does:
    1. Fetches full-season predictor stats (FanGraphs + Statcast, years 2022–2024)
    2. Fetches full-season target stats   (FanGraphs, years 2023–2025)
    3. Cross-season merge on stable FanGraphs player ID (IDfg)
    4. Applies PA filters, imputes NaN features
    5. Trains ElasticNetCV, RandomForestRegressor, OLS per target
    6. Evaluates with leave-one-season-out GroupKFold CV
    7. Saves CSV / JSON / plot outputs

All outputs:
    results/csv/hitter_model_dataset.csv
    results/csv/model_performance_summary.csv       — count targets
    results/csv/elastic_net_features.csv
    results/csv/random_forest_importances.csv
    results/csv/ols_coefficients.csv
    results/csv/rate_model_performance_summary.csv  — rate targets (NEW)
    results/csv/rate_elastic_net_features.csv       — rate targets (NEW)
    results/csv/rate_random_forest_importances.csv  — rate targets (NEW)
    results/csv/player_skill_scores.csv             — power/contact/speed (NEW)
    results/csv/breakout_candidates.csv             — ranked breakout scores (NEW)
    results/json/target_feature_rankings.json
    results/json/model_summary.json
    results/json/player_profiles.json
    results/json/player_skill_scores.json           — website player cards (NEW)
    results/json/website_feature_drivers.json       — frontend feature panels (NEW)
    results/plots/importance_<TARGET>.png  (one per target)

NOTE — half-season split design:
    The previous design used pybaseball.batting_stats_range() (BRef scraping)
    for first-half predictors and second-half targets.  That approach was retired
    because BRef range scraping throws "list index out of range" errors.
    If you want to revisit a half-season split, derive date-window aggregations
    from raw Statcast pitch-level data (pybaseball.statcast(start_dt, end_dt))
    rather than BRef scraping.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

_here = Path(__file__).parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import pybaseball

import config as cfg
from dataset_builder import build_modeling_dataset, load_modeling_dataset
from modeling import run_all_models, run_rate_models
from reporting import save_all_results
from skill_scores import (
    compute_skill_scores,
    compute_breakout_candidates,
)


def _configure_logging() -> None:
    # Use utf-8 on the stream handler so non-ASCII chars from any library
    # don't crash the Windows cp1252 console.
    stream_handler = logging.StreamHandler(sys.stdout)
    try:
        stream_handler.stream = open(
            sys.stdout.fileno(), mode="w", encoding="utf-8",
            buffering=1, closefd=False,
        )
    except Exception:
        pass  # fall back to the default encoding if reconfiguration fails

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s - %(message)s",
        handlers=[
            stream_handler,
            logging.FileHandler(_here / "pipeline.log", mode="a", encoding="utf-8"),
        ],
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MLB hitter year-over-year modeling pipeline",
    )
    parser.add_argument(
        "--skip-data",
        action="store_true",
        help="Load previously saved dataset instead of re-fetching.",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip matplotlib importance plots.",
    )
    parser.add_argument(
        "--pairs",
        type=str,
        default=None,
        help=(
            "Comma-separated PREDICTOR seasons to include "
            "(must match entries in config.SEASON_PAIRS). "
            "Example: --pairs 2022,2023,2024  "
            "Default: all active pairs in config.SEASON_PAIRS."
        ),
    )
    return parser.parse_args()


def _filter_pairs(requested_pred_seasons: list[int]) -> list[dict]:
    """Return only SEASON_PAIRS whose predictor_season is in requested_pred_seasons."""
    available = {p["predictor_season"]: p for p in cfg.SEASON_PAIRS}
    result = []
    for s in requested_pred_seasons:
        if s in available:
            result.append(available[s])
        else:
            logging.getLogger(__name__).warning(
                "Predictor season %d not found in config.SEASON_PAIRS — skipping.", s
            )
    return result


def main() -> None:
    _configure_logging()
    logger = logging.getLogger(__name__)
    args   = _parse_args()

    pybaseball.cache.enable()

    # ── Optionally restrict which pairs to run ─────────────────────────────────
    if args.pairs:
        requested = [int(s.strip()) for s in args.pairs.split(",")]
        active = _filter_pairs(requested)
        if not active:
            logger.error("No valid pairs found for --pairs argument. Aborting.")
            sys.exit(1)
        cfg.SEASON_PAIRS[:] = active
        logger.info(
            "Running with pairs: %s",
            [f"{p['predictor_season']}→{p['target_season']}" for p in active],
        )
    else:
        logger.info(
            "Running with all active pairs: %s",
            [f"{p['predictor_season']}→{p['target_season']}" for p in cfg.SEASON_PAIRS],
        )

    start = time.time()
    logger.info("=" * 60)
    logger.info("  MLB Hitter Modeling Pipeline (year-over-year) — Starting")
    logger.info("=" * 60)

    # ── Step 1: Build or load dataset ─────────────────────────────────────────
    if args.skip_data:
        logger.info("--skip-data: loading previously saved dataset…")
        try:
            modeling_df = load_modeling_dataset()
            logger.info("Loaded saved dataset: %d rows", len(modeling_df))
        except FileNotFoundError:
            logger.warning("No saved dataset found — fetching fresh data.")
            modeling_df = build_modeling_dataset(impute=True, save=True)
    else:
        modeling_df = build_modeling_dataset(impute=True, save=True)

    logger.info(
        "Modeling dataset: %d player-season-pairs | %d columns",
        len(modeling_df), len(modeling_df.columns),
    )

    if len(modeling_df) < 30:
        logger.warning(
            "Dataset has only %d rows — consider lowering MIN_PA_PREDICTOR_SEASON "
            "or adding more season pairs.",
            len(modeling_df),
        )

    # ── Step 2: Train main count-target models ────────────────────────────────
    logger.info("Training main models for targets: %s", cfg.TARGET_STATS)
    model_results = run_all_models(modeling_df)

    # ── Step 3: Train rate-based skill models ─────────────────────────────────
    # Rate targets (HR_rate, R_rate, RBI_rate, SB_rate) remove the PA confound
    # and measure pure skill.  SB_rate also receives times_on_base_proxy and
    # team_runs_scored to address the weakness of skill-only SB prediction.
    logger.info("Training rate-based skill models for targets: %s", cfg.RATE_TARGETS)
    rate_model_results = run_rate_models(modeling_df)

    # ── Step 4: Compute player skill scores and breakout candidates ────────────
    # Skill scores use ElasticNet coefficients from the rate models as weights
    # and normalise each metric as a z-score within its predictor season.
    logger.info("Computing player skill scores (power / contact / speed)...")
    df_with_scores = compute_skill_scores(
        modeling_df, rate_model_results, main_model_results=model_results
    )
    breakout_df = compute_breakout_candidates(df_with_scores)

    # ── Step 5: Save all outputs ───────────────────────────────────────────────
    save_all_results(
        model_results=model_results,
        modeling_df=modeling_df,
        rate_model_results=rate_model_results,
        skill_scores_df=df_with_scores,
        breakout_df=breakout_df,
        plots=not args.no_plots,
    )

    elapsed = time.time() - start

    # ── Final summary ──────────────────────────────────────────────────────────
    n_rows       = len(modeling_df)
    n_predictors = len([c for c in cfg.ALL_PREDICTORS if c in modeling_df.columns])
    n_pairs      = int(modeling_df["predictor_season"].nunique())

    logger.info("=" * 60)
    logger.info("  PIPELINE SUMMARY")
    logger.info("  Total player-season rows : %d", n_rows)
    logger.info("  Season pairs             : %d  (%s)",
                n_pairs,
                ", ".join(
                    f"{p['predictor_season']}->{p['target_season']}"
                    for p in cfg.SEASON_PAIRS
                ))
    logger.info("  Base predictors used     : %d", n_predictors)
    logger.info("")
    logger.info("  MAIN MODEL CV-R2 (leave-one-season-out):")
    for tgt, res in model_results.items():
        en_r2 = res.get("elastic_net",   {}).get("cv_r2_mean", float("nan"))
        rf_r2 = res.get("random_forest", {}).get("cv_r2_mean", float("nan"))
        logger.info("    next_%-5s   ElasticNet=%.3f   RF=%.3f", tgt, en_r2, rf_r2)
    logger.info("")
    logger.info("  RATE MODEL CV-R2 (leave-one-season-out):")
    for tgt, res in rate_model_results.items():
        en_r2 = res.get("elastic_net",   {}).get("cv_r2_mean", float("nan"))
        rf_r2 = res.get("random_forest", {}).get("cv_r2_mean", float("nan"))
        logger.info("    next_%-10s  ElasticNet=%.3f   RF=%.3f", tgt, en_r2, rf_r2)
    logger.info("")
    logger.info("  NEW OUTPUT FILES:")
    new_files = [
        cfg.RESULTS_CSV_DIR  / "rate_model_performance_summary.csv",
        cfg.RESULTS_CSV_DIR  / "rate_random_forest_importances.csv",
        cfg.RESULTS_CSV_DIR  / "rate_elastic_net_features.csv",
        cfg.RESULTS_CSV_DIR  / "player_skill_scores.csv",
        cfg.RESULTS_CSV_DIR  / "breakout_candidates.csv",
        cfg.RESULTS_JSON_DIR / "player_skill_scores.json",
        cfg.RESULTS_JSON_DIR / "website_feature_drivers.json",
    ]
    for p in new_files:
        status = "OK     " if p.exists() else "MISSING"
        logger.info("    [%s]  %s", status, p.name)
    logger.info("")
    logger.info("  Pipeline complete in %.1f seconds", elapsed)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

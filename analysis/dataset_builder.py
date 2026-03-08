"""
Assemble the final modeling dataset by merging predictor features (year N) with
next-season targets (year N+1) across all active SEASON_PAIRS.

Design — year-over-year stacking:
    For each pair {predictor_season=N, target_season=N+1}:
        1. Build predictor features for season N  (feature_builder.py)
        2. Build targets for season N+1           (target_builder.py)
        3. Merge on stable FanGraphs player ID (fg_id), with normalised name
           as fallback for players whose ID couldn't be resolved
        4. Apply PA filters (predictor season and optionally target season)
        5. Tag rows with predictor_season and target_season

    Rows from all pairs are stacked into one DataFrame:
        ~150–200 rows per pair × 3 pairs ≈ 450–600 total rows

    The `predictor_season` column is used in modeling.py as the GroupKFold
    grouping variable, enabling proper leave-one-season-out evaluation.

Outputs:
    results/csv/hitter_model_dataset.csv
    data/processed/hitter_model_dataset.parquet

API endpoint note:
    The combined DataFrame could be returned directly from a future
    /api/analysis/dataset endpoint for website consumption.
"""

import logging

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

from config import (
    ALL_PREDICTORS,
    DATA_PROCESSED_DIR,
    EXCLUDED_FROM_PREDICTORS,
    IMPUTATION_STRATEGY,
    MIN_PA_PREDICTOR_SEASON,
    MIN_PA_TARGET_SEASON,
    RESULTS_CSV_DIR,
    SB_EXTRA_PREDICTORS,
    SEASON_PAIRS,
    TARGET_STATS,
)
from data_sources import fetch_fg_batting_full
from feature_builder import build_predictor_features
from target_builder import build_targets
from utils import normalize_fg_id

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _merge_pair(pair: dict) -> pd.DataFrame:
    """
    Build and merge predictor features with next-season targets for one pair.

    Merge key: fg_id (FanGraphs player ID — stable across seasons).
    Fallback:  norm_name (normalised player name) for rows where fg_id is None.

    Returns a DataFrame with one row per qualifying player-season-pair.
    """
    pred_season   = pair["predictor_season"]
    target_season = pair["target_season"]

    logger.info(
        "Merging pair: predictor=%d → target=%d", pred_season, target_season
    )

    features = build_predictor_features(pred_season)
    targets  = build_targets(target_season)

    logger.info(
        "Pre-merge counts — features: %d players | targets: %d players",
        len(features), len(targets),
    )

    # ── Normalize fg_id dtype on both sides (Int64) ───────────────────────────
    # This is the final safety net.  feature_builder and target_builder already
    # call normalize_fg_id internally, but calling it here again is a no-op if
    # the dtype is already Int64, and a guard against any cached DataFrames that
    # were created before this fix was applied.
    if "fg_id" in features.columns:
        features = features.copy()
        features["fg_id"] = normalize_fg_id(features["fg_id"])
    if "fg_id" in targets.columns:
        targets = targets.copy()
        targets["fg_id"] = normalize_fg_id(targets["fg_id"])

    # ── Diagnostic logging ────────────────────────────────────────────────────
    feat_id_dtype  = features["fg_id"].dtype if "fg_id" in features.columns else "N/A"
    tgt_id_dtype   = targets["fg_id"].dtype  if "fg_id" in targets.columns  else "N/A"
    feat_id_nonnull = int(features["fg_id"].notna().sum()) if "fg_id" in features.columns else 0
    tgt_id_nonnull  = int(targets["fg_id"].notna().sum())  if "fg_id" in targets.columns  else 0
    logger.info(
        "fg_id dtype    — features: %s | targets: %s",
        feat_id_dtype, tgt_id_dtype,
    )
    logger.info(
        "fg_id non-null — features: %d / %d | targets: %d / %d",
        feat_id_nonnull, len(features), tgt_id_nonnull, len(targets),
    )
    if "fg_id" in features.columns and "fg_id" in targets.columns:
        feat_ids  = set(features["fg_id"].dropna().astype(int))
        tgt_ids   = set(targets["fg_id"].dropna().astype(int))
        overlap   = feat_ids & tgt_ids
        logger.info(
            "fg_id overlap before merge: %d players (feat only: %d | tgt only: %d)",
            len(overlap),
            len(feat_ids - tgt_ids),
            len(tgt_ids - feat_ids),
        )

    # ── Primary merge on fg_id ────────────────────────────────────────────────
    feat_id   = features[features["fg_id"].notna()].copy()
    feat_noID = features[features["fg_id"].isna()].copy()
    tgt_id    = targets[targets["fg_id"].notna()].copy()
    tgt_noID  = targets[targets["fg_id"].isna()].copy()

    merged_id = feat_id.merge(
        tgt_id.drop(columns=["norm_name"], errors="ignore"),
        on="fg_id",
        how="inner",
    )

    # ── Fallback merge on norm_name ───────────────────────────────────────────
    # For players whose fg_id couldn't be resolved in either table
    tgt_noID_clean = tgt_noID.drop(columns=["fg_id"], errors="ignore")
    merged_name = pd.DataFrame()
    if not feat_noID.empty and not tgt_noID_clean.empty:
        merged_name = feat_noID.merge(
            tgt_noID_clean,
            on="norm_name",
            how="inner",
        )

    # ── Combine and tag ───────────────────────────────────────────────────────
    combined = pd.concat([merged_id, merged_name], ignore_index=True)

    # Remove accidental duplicates (player matched by both passes)
    combined = combined.drop_duplicates(subset=["fg_id", "norm_name"], keep="first")

    # Tag columns
    combined["predictor_season"] = pred_season
    combined["target_season"]    = target_season

    logger.info(
        "After merge: %d player-season pairs (from %d features, %d targets)",
        len(combined), len(features), len(targets),
    )

    # ── Apply predictor-season PA filter ─────────────────────────────────────
    pa_pred_col = "pa_predictor_season"
    if pa_pred_col in combined.columns and MIN_PA_PREDICTOR_SEASON > 0:
        before = len(combined)
        pa_vals = pd.to_numeric(combined[pa_pred_col], errors="coerce").fillna(0)
        combined = combined[pa_vals >= MIN_PA_PREDICTOR_SEASON].copy()
        logger.info(
            "Predictor PA filter (≥ %d): %d → %d players",
            MIN_PA_PREDICTOR_SEASON, before, len(combined),
        )
    else:
        logger.warning(
            "'%s' column not found — predictor PA filter not applied.", pa_pred_col
        )

    # ── Apply target-season PA filter (optional) ─────────────────────────────
    if MIN_PA_TARGET_SEASON > 0 and "next_PA" in combined.columns:
        before = len(combined)
        pa_vals = pd.to_numeric(combined["next_PA"], errors="coerce").fillna(0)
        combined = combined[pa_vals >= MIN_PA_TARGET_SEASON].copy()
        logger.info(
            "Target PA filter (≥ %d): %d → %d players",
            MIN_PA_TARGET_SEASON, before, len(combined),
        )

    # ── Drop residual excluded-outcome columns ────────────────────────────────
    bad = [c for c in combined.columns if c.lower() in EXCLUDED_FROM_PREDICTORS]
    if bad:
        logger.warning("Dropping excluded columns: %s", bad)
        combined.drop(columns=bad, inplace=True)

    return combined.reset_index(drop=True)


def _validate_no_leakage(df: pd.DataFrame) -> None:
    """
    Raise ValueError if any excluded outcome stat appears as a predictor column.
    Target columns (next_*) are outputs and are explicitly exempt.
    """
    lower_cols = set(c.lower() for c in df.columns)
    violations = lower_cols & EXCLUDED_FROM_PREDICTORS
    # Exempt target output columns (next_hr, etc.)
    violations = {v for v in violations if not v.startswith("next_")}
    if violations:
        raise ValueError(
            f"Target leakage detected — excluded outcome stats in columns: "
            f"{sorted(violations)}"
        )


# ── Public entry points ───────────────────────────────────────────────────────

def build_modeling_dataset(
    impute: bool = True,
    save: bool = True,
) -> pd.DataFrame:
    """
    Build the complete year-over-year modeling dataset across all SEASON_PAIRS.

    Steps:
        1. For each pair, merge predictor features with next-season targets.
        2. Stack all pairs into one DataFrame.
        3. Guard against target leakage.
        4. Impute missing predictor values (median strategy by default).
        5. Save to CSV and parquet.

    Args:
        impute: Impute NaN predictor values using IMPUTATION_STRATEGY.
        save:   Write outputs to results/csv/ and data/processed/.

    Returns:
        Modeling DataFrame with columns:
            predictor_season, target_season,
            fg_id, norm_name, name_raw_fg, team_fg,
            <ALL_PREDICTORS>,
            next_HR, next_R, next_RBI, next_SB, next_AVG,
            next_PA  (context)

    Modeling note on `predictor_season`:
        This column is used as the GroupKFold grouping variable in modeling.py.
        Training on seasons {2022, 2023} and testing on {2024} (and vice versa)
        gives a genuine leave-one-season-out estimate of predictive skill —
        far more meaningful than within-season K-fold CV.
    """
    pair_dfs: list[pd.DataFrame] = []

    for pair in SEASON_PAIRS:
        try:
            df = _merge_pair(pair)
            if df.empty:
                logger.warning(
                    "Pair %d→%d produced 0 rows — skipping.",
                    pair["predictor_season"], pair["target_season"],
                )
                continue
            pair_dfs.append(df)
        except Exception as exc:
            logger.error(
                "Failed pair %d→%d: %s — skipping.",
                pair["predictor_season"], pair["target_season"], exc,
            )

    if not pair_dfs:
        raise RuntimeError(
            "No season pairs could be assembled.  Check logs above."
        )

    combined = pd.concat(pair_dfs, ignore_index=True)
    logger.info(
        "Combined dataset: %d player-season-pairs across %d season pairs",
        len(combined), len(pair_dfs),
    )

    # Count rows per pair for diagnostics
    for (ps, ts), grp in combined.groupby(["predictor_season", "target_season"]):
        logger.info("  %d→%d: %d rows", ps, ts, len(grp))

    # Safety: no leakage
    _validate_no_leakage(combined)

    # ── Compute rate targets (next_*_rate = next_* / next_PA) ─────────────────
    # Rate targets isolate skill from playing time; used in the second modeling
    # layer (run_rate_models in modeling.py) without changing the count-target layer.
    # next_* columns start with "next_" so they are exempt from leakage checks.
    if "next_PA" in combined.columns:
        for stat in ["HR", "R", "RBI", "SB"]:
            src_col  = f"next_{stat}"
            rate_col = f"next_{stat}_rate"
            if src_col in combined.columns:
                pa_vals   = pd.to_numeric(combined["next_PA"],  errors="coerce")
                stat_vals = pd.to_numeric(combined[src_col], errors="coerce")
                # Guard against division by zero — treat next_PA = 0 as missing
                combined[rate_col] = stat_vals / pa_vals.where(pa_vals > 0)
                logger.info(
                    "Computed %s: %d non-null values (%.1f%%)",
                    rate_col,
                    combined[rate_col].notna().sum(),
                    100 * combined[rate_col].notna().mean(),
                )
    else:
        logger.warning(
            "next_PA column not found — rate targets (next_*_rate) not computed."
        )

    # ── Missing-value summary ──────────────────────────────────────────────────
    pred_cols = [c for c in ALL_PREDICTORS if c in combined.columns]
    nan_summary = combined[pred_cols].isna().sum()
    nan_cols = nan_summary[nan_summary > 0].sort_values(ascending=False)
    if not nan_cols.empty:
        logger.info(
            "Features with NaN values before imputation:\n%s",
            nan_cols.to_string(),
        )

    # ── Imputation ─────────────────────────────────────────────────────────────
    if impute and pred_cols:
        pre_nan_mask = combined[pred_cols].isna().any(axis=1)
        imputer = SimpleImputer(strategy=IMPUTATION_STRATEGY)
        combined[pred_cols] = imputer.fit_transform(combined[pred_cols])
        combined["had_imputed_features"] = pre_nan_mask
        logger.info("Imputation complete (strategy='%s').", IMPUTATION_STRATEGY)

    # ── SB-specific supplemental features ─────────────────────────────────────
    # Computed AFTER base-feature imputation so inputs are always non-NaN.
    # These are added only for SB/SB_rate models (see SB_EXTRA_PREDICTORS in config).

    # times_on_base_proxy ≈ PA × (BB% + contact% × 0.30)
    # Logic: BB% captures free passes; contact% × 0.30 approximates hit rate
    # (rough BABIP proxy).  The product with PA gives a rough "times on base" count.
    if "pa_predictor_season" in combined.columns and "bb_pct" in combined.columns:
        pa      = combined["pa_predictor_season"].astype(float)
        bb      = combined["bb_pct"].astype(float)
        contact = (
            combined["contact_pct"].astype(float)
            if "contact_pct" in combined.columns
            else pd.Series(0.75, index=combined.index)
        )
        obp_proxy = bb + contact * 0.30
        combined["times_on_base_proxy"] = (pa * obp_proxy).round(2)
        logger.info(
            "Computed times_on_base_proxy: %d non-null values",
            combined["times_on_base_proxy"].notna().sum(),
        )

    # team_runs_scored: aggregate R per team from cached FanGraphs player data.
    # Avoids a new API call by reusing data already fetched by feature_builder.
    # Players on high-run teams have more stolen-base opportunities.
    combined["team_runs_scored"] = np.nan
    for pred_season in sorted(combined["predictor_season"].astype(int).unique()):
        try:
            fg_raw = fetch_fg_batting_full(pred_season)
            if "R" not in fg_raw.columns or "Team" not in fg_raw.columns:
                logger.warning(
                    "FG data for %d missing R or Team — team_runs_scored unavailable.",
                    pred_season,
                )
                continue
            # Exclude multi-team stint rows (FanGraphs marks them with "-")
            fg_single = fg_raw[
                ~fg_raw["Team"].astype(str).str.strip().isin(["- - -", "TOT", "---", "2TM", "3TM"])
            ]
            team_r_map: dict = (
                fg_single.groupby("Team")["R"]
                .sum()
                .apply(lambda v: float(pd.to_numeric(v, errors="coerce")))
                .to_dict()
            )
            mask = combined["predictor_season"].astype(int) == pred_season
            combined.loc[mask, "team_runs_scored"] = (
                combined.loc[mask, "team_fg"].map(team_r_map)
            )
            n_mapped = int(combined.loc[mask, "team_runs_scored"].notna().sum())
            logger.info(
                "team_runs_scored for %d: %d/%d players mapped",
                pred_season, n_mapped, int(mask.sum()),
            )
        except Exception as exc:
            logger.warning(
                "Could not compute team_runs_scored for %d: %s", pred_season, exc
            )

    # Impute SB extras (median) in case of any gaps (e.g., unmatched team names)
    sb_extras_present = [c for c in SB_EXTRA_PREDICTORS if c in combined.columns]
    if sb_extras_present:
        sb_imputer = SimpleImputer(strategy=IMPUTATION_STRATEGY)
        combined[sb_extras_present] = sb_imputer.fit_transform(combined[sb_extras_present])
        logger.info("Imputed SB extra predictors: %s", sb_extras_present)

    # ── Target NaN report ─────────────────────────────────────────────────────
    for col in [f"next_{s}" for s in TARGET_STATS]:
        if col in combined.columns:
            n = combined[col].isna().sum()
            if n:
                logger.warning(
                    "Target '%s' has %d NaN rows — excluded per-target during modeling.",
                    col, n,
                )

    # ── Save ───────────────────────────────────────────────────────────────────
    if save:
        csv_path     = RESULTS_CSV_DIR    / "hitter_model_dataset.csv"
        parquet_path = DATA_PROCESSED_DIR / "hitter_model_dataset.parquet"
        combined.to_csv(csv_path, index=False)
        combined.to_parquet(parquet_path, index=False)
        logger.info("Saved → %s  (%d rows)", csv_path, len(combined))
        logger.info("Saved → %s", parquet_path)

    return combined


def load_modeling_dataset() -> pd.DataFrame:
    """Load the most recently saved modeling dataset (parquet → CSV fallback)."""
    parquet_path = DATA_PROCESSED_DIR / "hitter_model_dataset.parquet"
    csv_path     = RESULTS_CSV_DIR    / "hitter_model_dataset.csv"

    if parquet_path.exists():
        logger.info("Loading dataset from parquet: %s", parquet_path)
        return pd.read_parquet(parquet_path)
    elif csv_path.exists():
        logger.info("Loading dataset from CSV: %s", csv_path)
        return pd.read_csv(csv_path)
    else:
        raise FileNotFoundError(
            "No saved dataset found.  Run build_modeling_dataset() first."
        )

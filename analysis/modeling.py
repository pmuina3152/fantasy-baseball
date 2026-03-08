"""
Train predictive models for each next-season fantasy target.

Models trained per target (HR, R, RBI, SB, AVG):
    1. ElasticNetCV         — regularised linear model; non-zero coefficients
                              identify which process metrics survive penalisation.
    2. RandomForestRegressor — nonlinear ensemble; feature importances are
                              averaged over 300 trees and robust to collinearity.
    3. OLS (statsmodels)    — fit on the top-N features selected by ElasticNet /
                              RF; produces coefficients, p-values, and R² for
                              human interpretability.

Evaluation strategy — LEAVE-ONE-SEASON-OUT cross-validation:
    With year-over-year season pairs stacked (2022→2023, 2023→2024, 2024→2025),
    the `predictor_season` column is used as the GroupKFold group label.

    Each fold trains on all season pairs EXCEPT one, then tests on the held-out
    season pair.  With 3 pairs this yields 3 folds, each of which is a genuine
    out-of-sample prediction:
        Fold 1: Train {2022→2023, 2023→2024}  →  Test {2024→2025}
        Fold 2: Train {2022→2023, 2024→2025}  →  Test {2023→2024}
        Fold 3: Train {2023→2024, 2024→2025}  →  Test {2022→2023}

    This is the gold-standard evaluation design for this kind of time-series
    prediction task.  The resulting R² reflects real predictive skill across
    different seasons, not within-season pattern matching.

    Fallback: if only one unique season group exists (e.g., data collection
    failed for all but one pair), the evaluation falls back to standard K-fold
    CV with a warning.

API endpoint note:
    run_all_models() returns a structured dict that a future
    /api/analysis/models endpoint could serialise directly as JSON.
"""

import logging
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import ElasticNetCV
from sklearn.model_selection import GroupKFold, KFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import statsmodels.api as sm

from config import (
    ALL_PREDICTORS,
    CV_FOLDS,
    ELASTICNET_L1_RATIOS,
    OLS_TOP_N_FEATURES,
    RANDOM_STATE,
    RATE_TARGETS,
    RF_MAX_FEATURES,
    RF_MIN_SAMPLES_LEAF,
    RF_N_ESTIMATORS,
    SB_EXTRA_PREDICTORS,
    TARGET_STATS,
)

logger = logging.getLogger(__name__)


# ── Data preparation ──────────────────────────────────────────────────────────

def prepare_Xy(
    df: pd.DataFrame,
    target: str,
    extra_features: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.Series, list[str], np.ndarray]:
    """
    Extract X (predictor matrix), y (target vector), feature names, and
    groups (predictor_season array for GroupKFold) from the modeling DataFrame.

    Rows with NaN in the target column are excluded.
    Zero-variance features are dropped to avoid numerical issues.

    Args:
        df:             Modeling dataset from dataset_builder.build_modeling_dataset().
        target:         Target name (e.g., "HR", "HR_rate").  Column "next_{target}" must exist.
        extra_features: Optional list of additional feature columns to include on top of
                        ALL_PREDICTORS.  Used to inject SB_EXTRA_PREDICTORS for SB models
                        without polluting the global predictor set.

    Returns:
        (X, y, feature_names, groups)
    """
    target_col = f"next_{target}"
    if target_col not in df.columns:
        raise KeyError(f"Target column '{target_col}' not in dataset.")

    available = [c for c in ALL_PREDICTORS if c in df.columns]
    if extra_features:
        for ef in extra_features:
            if ef in df.columns and ef not in available:
                available.append(ef)
    sub = df[df[target_col].notna()].copy()

    X = sub[available].copy()
    y = pd.to_numeric(sub[target_col], errors="coerce")

    # Drop rows where y is still NaN
    valid = y.notna()
    X, y = X[valid], y[valid]
    sub = sub[valid]

    # Groups for leave-one-season-out CV
    if "predictor_season" in sub.columns:
        groups = sub["predictor_season"].values
    else:
        groups = np.zeros(len(y), dtype=int)

    # Drop zero-variance features
    std = X.std(ddof=1)
    zero_var = std[std == 0].index.tolist()
    if zero_var:
        logger.debug("Dropping zero-variance features for '%s': %s", target, zero_var)
        X = X.drop(columns=zero_var)

    feature_names = list(X.columns)
    n_seasons     = len(np.unique(groups))
    logger.info(
        "Target '%s': %d samples across %d season groups | %d features",
        target, len(y), n_seasons, len(feature_names),
    )
    return X, y, feature_names, groups


def _build_cv(groups: np.ndarray):
    """
    Return the appropriate cross-validation object.

    Uses GroupKFold(n_splits=n_groups) when ≥2 unique season groups exist.
    This gives leave-one-season-out evaluation.

    Falls back to KFold(CV_FOLDS) with a warning if only 1 group is present.
    """
    unique_groups = np.unique(groups)
    n_groups = len(unique_groups)

    if n_groups >= 2:
        logger.info(
            "CV: GroupKFold(%d) — leave-one-season-out (groups: %s)",
            n_groups, sorted(unique_groups.tolist()),
        )
        return GroupKFold(n_splits=n_groups), groups
    else:
        logger.warning(
            "Only 1 unique season group found — falling back to KFold(%d). "
            "Results represent within-season predictability, not true out-of-sample skill.",
            CV_FOLDS,
        )
        return KFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE), None


# ── ElasticNetCV ──────────────────────────────────────────────────────────────

def fit_elasticnet(
    X: pd.DataFrame,
    y: pd.Series,
    feature_names: list[str],
    groups: np.ndarray,
) -> dict:
    """
    Fit a StandardScaler → ElasticNetCV pipeline with leave-one-season-out CV.

    Returns:
        model, selected_features, coeff_df, cv_r2_mean, cv_r2_std, alpha, l1_ratio
    """
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("enet",   ElasticNetCV(
            l1_ratio=ELASTICNET_L1_RATIOS,
            cv=CV_FOLDS,       # inner CV for alpha/l1_ratio selection
            max_iter=10_000,
            random_state=RANDOM_STATE,
            n_jobs=-1,
        )),
    ])

    cv_obj, cv_groups = _build_cv(groups)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cv_kwargs = {"groups": cv_groups} if cv_groups is not None else {}
        cv_scores = cross_val_score(
            pipeline, X, y, cv=cv_obj, scoring="r2", n_jobs=-1, **cv_kwargs
        )
        pipeline.fit(X, y)

    enet   = pipeline.named_steps["enet"]
    coeffs = enet.coef_

    coeff_df = pd.DataFrame({
        "feature":   feature_names,
        "std_coeff": coeffs,
        "abs_coeff": np.abs(coeffs),
    }).sort_values("abs_coeff", ascending=False).reset_index(drop=True)

    selected = coeff_df[coeff_df["abs_coeff"] > 0]["feature"].tolist()

    return {
        "model":             pipeline,
        "selected_features": selected,
        "coeff_df":          coeff_df,
        "cv_r2_mean":        float(cv_scores.mean()),
        "cv_r2_std":         float(cv_scores.std()),
        "alpha":             float(enet.alpha_),
        "l1_ratio":          float(enet.l1_ratio_),
    }


# ── Random Forest ─────────────────────────────────────────────────────────────

def fit_random_forest(
    X: pd.DataFrame,
    y: pd.Series,
    feature_names: list[str],
    groups: np.ndarray,
) -> dict:
    """
    Fit a RandomForestRegressor with leave-one-season-out cross-validation.

    Returns:
        model, importance_df, cv_r2_mean, cv_r2_std
    """
    rf = RandomForestRegressor(
        n_estimators=RF_N_ESTIMATORS,
        max_features=RF_MAX_FEATURES,
        min_samples_leaf=RF_MIN_SAMPLES_LEAF,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    cv_obj, cv_groups = _build_cv(groups)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cv_kwargs = {"groups": cv_groups} if cv_groups is not None else {}
        cv_scores = cross_val_score(
            rf, X, y, cv=cv_obj, scoring="r2", n_jobs=-1, **cv_kwargs
        )
        rf.fit(X, y)

    importance_df = pd.DataFrame({
        "feature":    feature_names,
        "importance": rf.feature_importances_,
    }).sort_values("importance", ascending=False).reset_index(drop=True)

    return {
        "model":         rf,
        "importance_df": importance_df,
        "cv_r2_mean":    float(cv_scores.mean()),
        "cv_r2_std":     float(cv_scores.std()),
    }


# ── OLS (statsmodels) ─────────────────────────────────────────────────────────

def fit_ols(
    X: pd.DataFrame,
    y: pd.Series,
    feature_names: list[str],
    top_features: list[str],
) -> dict:
    """
    Fit an OLS regression on the top-N features selected by ElasticNet + RF.

    Uses HC3 heteroskedasticity-robust standard errors.
    Features are standardised so coefficients reflect relative importance.

    Returns:
        results, coeff_df, r2, adj_r2, n_obs, top_features
    """
    use_features = [f for f in top_features if f in X.columns][:OLS_TOP_N_FEATURES]

    if len(use_features) < 2:
        logger.warning(
            "OLS: only %d features available — skipping.", len(use_features)
        )
        return {
            "results":      None,
            "coeff_df":     pd.DataFrame(),
            "r2":           np.nan,
            "adj_r2":       np.nan,
            "n_obs":        len(y),
            "top_features": use_features,
        }

    X_sub    = X[use_features].copy()
    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X_sub)
    X_sm     = sm.add_constant(
        pd.DataFrame(X_scaled, columns=use_features, index=X_sub.index)
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        results = sm.OLS(y.values, X_sm.values).fit(cov_type="HC3")

    labels = ["const"] + use_features

    # conf_int() returns a numpy ndarray of shape (n_params, 2) when the model
    # was built from numpy arrays.  results.conf_int()[0] gives the first ROW
    # (length 2), not the first column.  Use [:, 0] / [:, 1] for column slicing.
    ci     = np.asarray(results.conf_int())   # always a 2-D numpy array
    coeff_df = pd.DataFrame({
        "feature":       labels,
        "coeff":         results.params,
        "std_err":       results.bse,
        "t_stat":        results.tvalues,
        "p_value":       results.pvalues,
        "conf_int_low":  ci[:, 0],
        "conf_int_high": ci[:, 1],
    }).reset_index(drop=True)

    return {
        "results":      results,
        "coeff_df":     coeff_df,
        "r2":           float(results.rsquared),
        "adj_r2":       float(results.rsquared_adj),
        "n_obs":        int(results.nobs),
        "top_features": use_features,
    }


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_all_models(df: pd.DataFrame) -> dict:
    """
    Fit all three model types for each target variable.

    Args:
        df: Modeling dataset from dataset_builder.build_modeling_dataset().

    Returns:
        Nested dict keyed by target name:
        {
          "HR": {
            "n_samples":     int,
            "n_season_pairs": int,
            "feature_names": list[str],
            "elastic_net":   {...},
            "random_forest": {...},
            "ols":           {...},
          },
          ...
        }

    The cv_r2 values are leave-one-season-out R², which represent genuine
    out-of-sample predictive skill across different season contexts.

    API endpoint note:
        Non-model fields (cv_r2, selected_features, importance_df, coeff_df)
        can be serialised directly for a /api/analysis/model-results endpoint.
    """
    results: dict = {}

    for target in TARGET_STATS:
        logger.info("--- Fitting models for target: next_%s ---", target)

        # SB benefits from opportunity/context predictors not in the main feature set
        extra = SB_EXTRA_PREDICTORS if target == "SB" else None

        try:
            X, y, feature_names, groups = prepare_Xy(df, target, extra_features=extra)
        except (KeyError, ValueError) as exc:
            logger.error("Skipping target '%s': %s", target, exc)
            continue

        if len(y) < 20:
            logger.warning(
                "Target '%s' has only %d samples — results will be unreliable.",
                target, len(y),
            )

        n_pairs = len(np.unique(groups))

        # 1. ElasticNetCV
        logger.info("[%s] Fitting ElasticNetCV...", target)
        enet_res = fit_elasticnet(X, y, feature_names, groups)
        logger.info(
            "[%s] ElasticNet CV-R2=%.3f+/-%.3f | alpha=%.4f | l1=%.2f | "
            "%d/%d features selected",
            target,
            enet_res["cv_r2_mean"], enet_res["cv_r2_std"],
            enet_res["alpha"], enet_res["l1_ratio"],
            len(enet_res["selected_features"]), len(feature_names),
        )

        # 2. Random Forest
        logger.info("[%s] Fitting RandomForest...", target)
        rf_res = fit_random_forest(X, y, feature_names, groups)
        logger.info(
            "[%s] RF CV-R2=%.3f+/-%.3f",
            target, rf_res["cv_r2_mean"], rf_res["cv_r2_std"],
        )

        # 3. OLS on union of top ElasticNet + top RF features
        enet_top = enet_res["selected_features"][:OLS_TOP_N_FEATURES]
        rf_top   = rf_res["importance_df"]["feature"].head(OLS_TOP_N_FEATURES).tolist()
        combined_top: list[str] = []
        seen: set[str] = set()
        for f in enet_top + rf_top:
            if f not in seen:
                combined_top.append(f)
                seen.add(f)

        logger.info("[%s] Fitting OLS on features: %s", target, combined_top[:OLS_TOP_N_FEATURES])
        ols_res = fit_ols(X, y, feature_names, combined_top)
        if ols_res["results"] is not None:
            logger.info(
                "[%s] OLS R²=%.3f | Adj-R²=%.3f | n=%d",
                target, ols_res["r2"], ols_res["adj_r2"], ols_res["n_obs"],
            )

        results[target] = {
            "n_samples":      len(y),
            "n_season_pairs": n_pairs,
            "feature_names":  feature_names,
            "elastic_net":    enet_res,
            "random_forest":  rf_res,
            "ols":            ols_res,
        }

    logger.info("=== Modeling complete — %d targets fitted ===", len(results))
    return results


# ── Rate-target models (PART 1 extension) ────────────────────────────────────

def run_rate_models(df: pd.DataFrame) -> dict:
    """
    Fit ElasticNetCV, RandomForestRegressor, and OLS for each RATE_TARGET.

    Rate targets (HR_rate, R_rate, RBI_rate, SB_rate) are PA-normalised versions
    of the count targets.  They measure *skill* independently of playing time,
    which is valuable because PA is a dominant predictor of raw count totals.

    The model structure is identical to run_all_models(); only the target columns
    change.  Cross-validation strategy is the same leave-one-season-out GroupKFold.

    SB_rate additionally receives SB_EXTRA_PREDICTORS (times_on_base_proxy,
    team_runs_scored) to address the known weakness of skill-only SB prediction.

    Returns:
        Nested dict keyed by rate target name (e.g., "HR_rate"), same schema as
        run_all_models().

    API endpoint note:
        A future /api/analysis/rate-models endpoint could return this dict directly
        to power a "player skill ratings" panel on the website.
    """
    results: dict = {}

    for target in RATE_TARGETS:
        logger.info("--- Fitting rate model for target: next_%s ---", target)

        extra = SB_EXTRA_PREDICTORS if target == "SB_rate" else None

        try:
            X, y, feature_names, groups = prepare_Xy(df, target, extra_features=extra)
        except (KeyError, ValueError) as exc:
            logger.error("Skipping rate target '%s': %s", target, exc)
            continue

        if len(y) < 20:
            logger.warning(
                "Rate target '%s' has only %d samples — results may be unreliable.",
                target, len(y),
            )

        n_pairs = len(np.unique(groups))

        logger.info("[%s] Fitting ElasticNetCV...", target)
        enet_res = fit_elasticnet(X, y, feature_names, groups)
        logger.info(
            "[%s] ElasticNet CV-R2=%.3f+/-%.3f | alpha=%.4f | l1=%.2f | "
            "%d/%d features selected",
            target,
            enet_res["cv_r2_mean"], enet_res["cv_r2_std"],
            enet_res["alpha"], enet_res["l1_ratio"],
            len(enet_res["selected_features"]), len(feature_names),
        )

        logger.info("[%s] Fitting RandomForest...", target)
        rf_res = fit_random_forest(X, y, feature_names, groups)
        logger.info(
            "[%s] RF CV-R2=%.3f+/-%.3f",
            target, rf_res["cv_r2_mean"], rf_res["cv_r2_std"],
        )

        enet_top = enet_res["selected_features"][:OLS_TOP_N_FEATURES]
        rf_top   = rf_res["importance_df"]["feature"].head(OLS_TOP_N_FEATURES).tolist()
        combined_top: list[str] = []
        seen: set[str] = set()
        for f in enet_top + rf_top:
            if f not in seen:
                combined_top.append(f)
                seen.add(f)

        logger.info("[%s] Fitting OLS on features: %s", target, combined_top[:OLS_TOP_N_FEATURES])
        ols_res = fit_ols(X, y, feature_names, combined_top)
        if ols_res["results"] is not None:
            logger.info(
                "[%s] OLS R2=%.3f | Adj-R2=%.3f | n=%d",
                target, ols_res["r2"], ols_res["adj_r2"], ols_res["n_obs"],
            )

        results[target] = {
            "n_samples":      len(y),
            "n_season_pairs": n_pairs,
            "feature_names":  feature_names,
            "elastic_net":    enet_res,
            "random_forest":  rf_res,
            "ols":            ols_res,
        }

    logger.info("=== Rate modeling complete — %d targets fitted ===", len(results))
    return results

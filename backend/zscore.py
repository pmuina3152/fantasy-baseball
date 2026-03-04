"""
Z-score computation for fantasy baseball categories.

Counting stats (R, HR, RBI, SB, K, W, SV, HLD):
    z = (x - mean) / std  — standard z-score across the player pool

Rate stats (AVG, ERA, WHIP) use contribution-based weighting so that players
with more playing time carry proportionally more weight:

    AVG_contrib  = (playerAVG  - leagueAVG)  * AB        (higher AB amplifies edge)
    ERA_contrib  = (leagueERA  - playerERA)  * IP        (lower ERA → positive)
    WHIP_contrib = (leagueWHIP - playerWHIP) * IP        (lower WHIP → positive)

    z = (contrib - mean_contrib) / std_contrib

In all cases a higher z-score means better fantasy value.
"""

import numpy as np
import pandas as pd


def _zscore(series: pd.Series) -> pd.Series:
    """Sample z-score; returns 0 everywhere if std is 0 or NaN."""
    mean = series.mean()
    std = series.std(ddof=1)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


# ── Hitters ───────────────────────────────────────────────────────────────────

def compute_hitter_zscores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Counting stats — higher is better
    for cat in ["R", "HR", "RBI", "SB"]:
        df[f"z{cat}"] = _zscore(df[cat].astype(float))

    # AVG — contribution weighted by AB
    df["AVG"] = pd.to_numeric(df["AVG"], errors="coerce").fillna(0)
    df["AB"] = pd.to_numeric(df["AB"], errors="coerce").fillna(0)
    league_avg = df["AVG"].mean()
    avg_contrib = (df["AVG"] - league_avg) * df["AB"]
    df["zAVG"] = _zscore(avg_contrib)

    # Total z-score and 0–100 normalisation
    z_cols = ["zR", "zHR", "zRBI", "zSB", "zAVG"]
    df["total_z"] = df[z_cols].sum(axis=1)

    min_z, max_z = df["total_z"].min(), df["total_z"].max()
    df["score_0_100"] = (
        100.0 * (df["total_z"] - min_z) / (max_z - min_z)
        if max_z > min_z
        else 50.0
    )

    return df


# ── Pitchers ──────────────────────────────────────────────────────────────────

def compute_pitcher_zscores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in ["IP", "SO", "W", "SV", "HLD", "ERA", "WHIP"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Counting stats — higher is better
    for cat in ["SO", "W", "SV", "HLD"]:
        df[f"z{cat}"] = _zscore(df[cat].astype(float))

    # ERA — lower is better; contribution = (leagueERA - playerERA) * IP
    league_era = df["ERA"].mean()
    era_contrib = (league_era - df["ERA"]) * df["IP"]
    df["zERA"] = _zscore(era_contrib)

    # WHIP — lower is better; contribution = (leagueWHIP - playerWHIP) * IP
    league_whip = df["WHIP"].mean()
    whip_contrib = (league_whip - df["WHIP"]) * df["IP"]
    df["zWHIP"] = _zscore(whip_contrib)

    # Total z-score and 0–100 normalisation
    z_cols = ["zSO", "zW", "zSV", "zHLD", "zERA", "zWHIP"]
    df["total_z"] = df[z_cols].sum(axis=1)

    min_z, max_z = df["total_z"].min(), df["total_z"].max()
    df["score_0_100"] = (
        100.0 * (df["total_z"] - min_z) / (max_z - min_z)
        if max_z > min_z
        else 50.0
    )

    return df

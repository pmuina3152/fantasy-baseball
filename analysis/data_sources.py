"""
Raw data fetchers for the MLB hitter modeling pipeline.

Each function fetches one raw table from its upstream source (FanGraphs,
Baseball Reference, or Statcast via pybaseball) and caches the result to disk.
No feature engineering happens here — that is the responsibility of
feature_builder.py and target_builder.py.

Active data sources (year-over-year pipeline):
    1. FanGraphs full-season batting stats    → pybaseball.batting_stats()
       Used for BOTH predictor features (year N) and target extraction (year N+1).
    2. Statcast EV / barrel leaderboard       → pybaseball.statcast_batter_exitvelo_barrels()
    3. Sprint speed leaderboard               → pybaseball.statcast_sprint_speed()

Legacy / optional:
    4. BRef batting stats for a date range    → pybaseball.batting_stats_range()
       Previously used for half-season split modeling (first-half predictors →
       second-half targets).  That design was retired because BRef range scraping
       throws "list index out of range" errors and is generally brittle.
       Kept here for reference.  If a half-season design is revisited, the
       recommended approach is to aggregate raw Statcast pitch-level data
       (pybaseball.statcast(start_dt, end_dt)) rather than BRef scraping.
"""

import logging

import pandas as pd
import pybaseball

from utils import is_cache_valid, load_cache, retry, save_cache

logger = logging.getLogger(__name__)


# ── 1. FanGraphs full-season batting stats ────────────────────────────────────

def fetch_fg_batting_full(season: int) -> pd.DataFrame:
    """
    Full-season FanGraphs batting leaderboard (qual=1 = all players with ≥1 PA).

    Returns the raw FanGraphs DataFrame with all available columns.  Column
    names contain special characters (%, -, spaces) as returned by FanGraphs;
    renaming to snake_case happens in feature_builder.py.

    Typical columns of interest:
        Name, Team, Age, IDfg, PA, AB,
        BB%, K%, O-Swing%, Z-Swing%, Swing%, O-Contact%, Z-Contact%, Contact%,
        Whiff% (or SwStr%), GB%, FB%, LD%, Pull%, Cent%, Oppo%,
        EV, maxEV, LA, Barrel%, HardHit%, Spd

    NOTE: This is full-season data used as a skill proxy.  See module docstring.
    """
    name = f"fg_batting_full_{season}"
    if is_cache_valid(name):
        return load_cache(name)

    logger.info("Fetching FanGraphs full-season batting stats for %d…", season)
    df: pd.DataFrame = retry(lambda: pybaseball.batting_stats(season, qual=1))

    if df is None or df.empty:
        raise RuntimeError(
            f"pybaseball.batting_stats({season}) returned an empty DataFrame. "
            "Check that the season has started and FanGraphs is accessible."
        )

    logger.info(
        "FanGraphs batting %d: %d players, %d columns available: %s",
        season, len(df), len(df.columns), sorted(df.columns.tolist()),
    )
    save_cache(name, df)
    return df


# ── 2. BRef batting stats for a date range (LEGACY — not used in YoY pipeline) ─
#
# This function is retained for reference only.  The year-over-year pipeline
# uses fetch_fg_batting_full() for both predictor and target data, eliminating
# the need for BRef date-range scraping.
#
# If you want to experiment with a half-season split design, use raw Statcast
# pitch-level aggregations (pybaseball.statcast()) rather than this function.

def fetch_bref_batting_range(start_dt: str, end_dt: str) -> pd.DataFrame:
    """
    Baseball Reference batting stats for the given date window.

    Returns basic counting stats per player: PA, AB, H, 2B, 3B, HR, R, RBI,
    SB, CS, BB, SO, BA (renamed to AVG), OBP, SLG.

    Used for:
        • First-half window → derive true first-half BB% and K%, and PA count.
        • Second-half window → extract target stats (HR, R, RBI, SB, AVG).

    Multi-team players: BRef returns one row per team stint plus a "TOT" summary
    row.  This function deduplicates by keeping "TOT" where available, then
    aggregating remaining multi-row players by summing counting stats.

    Args:
        start_dt:  "YYYY-MM-DD" inclusive start of window.
        end_dt:    "YYYY-MM-DD" inclusive end of window.
    """
    safe  = f"{start_dt.replace('-', '')}_{end_dt.replace('-', '')}"
    cache_name = f"bref_batting_{safe}"

    if is_cache_valid(cache_name):
        return load_cache(cache_name)

    logger.info("Fetching BRef batting stats %s → %s…", start_dt, end_dt)
    df: pd.DataFrame = retry(
        lambda: pybaseball.batting_stats_range(start_dt, end_dt)
    )

    if df is None or df.empty:
        raise RuntimeError(
            f"pybaseball.batting_stats_range({start_dt!r}, {end_dt!r}) "
            "returned an empty DataFrame."
        )

    df = _normalize_bref_batting(df)
    df = _deduplicate_bref_multitenure(df)

    logger.info(
        "BRef batting %s → %s: %d players after dedup",
        start_dt, end_dt, len(df),
    )
    save_cache(cache_name, df)
    return df


def _normalize_bref_batting(df: pd.DataFrame) -> pd.DataFrame:
    """Rename BRef column variants to canonical names and strip name markers."""
    rename: dict[str, str] = {}

    # Batting average: BRef calls it 'BA'
    if "BA" in df.columns and "AVG" not in df.columns:
        rename["BA"] = "AVG"

    # Team column: BRef calls it 'Tm'
    if "Tm" in df.columns and "Team" not in df.columns:
        rename["Tm"] = "Team"

    if rename:
        df = df.rename(columns=rename)

    # Strip BRef handedness / marker characters from player names
    if "Name" in df.columns:
        df["Name"] = (
            df["Name"]
            .astype(str)
            .str.replace(r"[*#\\]", "", regex=True)
            .str.strip()
        )

    return df


# BRef counting columns we want to preserve and aggregate for multi-team players
_BREF_COUNT_COLS = ["PA", "AB", "H", "2B", "3B", "HR", "R", "RBI", "SB", "CS",
                    "BB", "IBB", "SO", "HBP", "SH", "SF", "GDP", "TB"]


def _deduplicate_bref_multitenure(df: pd.DataFrame) -> pd.DataFrame:
    """
    Handle players who appear on multiple teams in a single date-range pull.

    BRef includes one row per team stint and a "TOT" summary row for multi-team
    players.  Strategy:
        1. For players with a TOT row: keep only the TOT row.
        2. For players with multiple rows but no TOT: aggregate counting stats
           and recompute AVG from H / AB.
    """
    if "Name" not in df.columns:
        return df

    name_counts = df["Name"].value_counts()
    multi_names = set(name_counts[name_counts > 1].index)

    if not multi_names:
        return df

    single_df = df[~df["Name"].isin(multi_names)].copy()
    multi_df  = df[df["Name"].isin(multi_names)].copy()

    # Keep "TOT" rows where present
    has_team_col = "Team" in multi_df.columns
    if has_team_col:
        tot_rows      = multi_df[multi_df["Team"] == "TOT"]
        names_with_tot = set(tot_rows["Name"])
    else:
        tot_rows      = pd.DataFrame()
        names_with_tot = set()

    # Players without a TOT row need manual aggregation
    no_tot_multi = multi_df[~multi_df["Name"].isin(names_with_tot)]
    aggregated_rows = []
    if not no_tot_multi.empty:
        for pname, grp in no_tot_multi.groupby("Name"):
            row: dict = {"Name": pname}
            if has_team_col:
                row["Team"] = "TOT"

            # Sum counting stats
            for col in _BREF_COUNT_COLS:
                if col in grp.columns:
                    row[col] = pd.to_numeric(grp[col], errors="coerce").sum()

            # Recompute AVG from aggregated H / AB
            ab = row.get("AB", 0)
            h  = row.get("H",  0)
            row["AVG"] = (h / ab) if ab > 0 else 0.0

            # Carry through other columns (take first non-null value)
            for col in grp.columns:
                if col not in row:
                    val = grp[col].dropna().iloc[0] if not grp[col].dropna().empty else None
                    row[col] = val

            aggregated_rows.append(row)

    parts = [single_df, tot_rows]
    if aggregated_rows:
        parts.append(pd.DataFrame(aggregated_rows))

    return pd.concat(parts, ignore_index=True)


# ── 3. Statcast exit velocity / barrel leaderboard ────────────────────────────

def fetch_statcast_ev_barrels(season: int, min_bbe: int = 50) -> pd.DataFrame:
    """
    Statcast batted-ball leaderboard for the full season.

    Returns per-player aggregates including: avg EV, max EV, launch angle,
    sweet spot %, barrel %, hard hit %, ground ball %.
    Players are identified by MLBAM player_id.

    Args:
        season:   MLB season year.
        min_bbe:  Minimum batted-ball events required (filters noise).

    NOTE: Full-season endpoint only.  See module docstring.
    """
    cache_name = f"statcast_ev_barrels_{season}_{min_bbe}"
    if is_cache_valid(cache_name):
        return load_cache(cache_name)

    logger.info(
        "Fetching Statcast EV/barrel leaderboard for %d (min_bbe=%d)…",
        season, min_bbe,
    )
    try:
        df: pd.DataFrame = retry(
            lambda: pybaseball.statcast_batter_exitvelo_barrels(
                season, minBBE=min_bbe
            )
        )
    except Exception as exc:
        logger.warning(
            "statcast_batter_exitvelo_barrels(%d) failed: %s. "
            "Statcast EV/barrel features will be NaN for this season.",
            season, exc,
        )
        return pd.DataFrame()

    if df is None or df.empty:
        logger.warning("Statcast EV/barrel returned empty for %d.", season)
        return pd.DataFrame()

    logger.info("Statcast EV/barrel %d: %d players, columns: %s",
                season, len(df), sorted(df.columns.tolist()))
    save_cache(cache_name, df)
    return df


# ── 4. Sprint speed leaderboard ───────────────────────────────────────────────

def fetch_sprint_speed(season: int, min_opp: int = 10) -> pd.DataFrame:
    """
    Statcast sprint speed leaderboard for the full season.

    Returns per-player sprint_speed (ft/sec) and player_id (MLBAM).

    Tries multiple pybaseball function names because the API has been renamed
    across versions.  Falls back gracefully if unavailable.

    Args:
        season:   MLB season year.
        min_opp:  Minimum sprint opportunities required.

    NOTE: Full-season endpoint only.  See module docstring.
    """
    cache_name = f"sprint_speed_{season}_{min_opp}"
    if is_cache_valid(cache_name):
        return load_cache(cache_name)

    logger.info("Fetching sprint speed for %d (min_opp=%d)…", season, min_opp)

    df: pd.DataFrame | None = None
    # Try known pybaseball function names in order of preference
    for fn_name in ("statcast_sprint_speed", "statcast_running_splits"):
        fn = getattr(pybaseball, fn_name, None)
        if fn is None:
            continue
        try:
            df = retry(lambda: fn(season, min_opp=min_opp))
            logger.info("Sprint speed fetched via pybaseball.%s", fn_name)
            break
        except TypeError:
            # Some versions take positional-only args
            try:
                df = retry(lambda: fn(season))
                logger.info("Sprint speed fetched via pybaseball.%s (no min_opp)", fn_name)
                break
            except Exception as exc:
                logger.warning("pybaseball.%s(%d) also failed: %s", fn_name, season, exc)
        except Exception as exc:
            logger.warning("pybaseball.%s failed: %s", fn_name, exc)

    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        logger.warning(
            "Sprint speed data unavailable for %d — sprint_speed feature will be NaN.",
            season,
        )
        return pd.DataFrame()

    logger.info("Sprint speed %d: %d players, columns: %s",
                season, len(df), sorted(df.columns.tolist()))
    save_cache(cache_name, df)
    return df

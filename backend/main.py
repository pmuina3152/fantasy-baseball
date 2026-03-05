"""
Fantasy Baseball Z-Score API
Run with:  uvicorn main:app --reload --port 8000
"""

import logging
import os
import time as _time
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from config import (
    CACHE_MAX_AGE_HOURS,
    SEASON_END,
    TIMEFRAME_WINDOWS,
    VALID_TIMEFRAMES,
)
from data_fetcher import (
    fetch_batting,
    fetch_batting_range,
    fetch_pitching,
    fetch_pitching_range,
)
from zscore import compute_hitter_zscores, compute_pitcher_zscores

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fantasy Baseball Z-Score API",
    description="2025 MLB fantasy rankings powered by FanGraphs / pybaseball",
    version="2.0.0",
)

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://fantasy-baseball-six.vercel.app",
        "https://fantasy-baseball.vercel.app",
    ],
    allow_origin_regex=r"^https://fantasy-baseball-.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress responses ≥ 1 KB — significantly reduces JSON payload size over the wire
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── In-memory result cache ─────────────────────────────────────────────────────
# Avoids re-running heavy compute on every request within the TTL window.
# Key: "<endpoint>:<season>:<timeframe>"  Value: (timestamp_float, data)
_MEM_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = CACHE_MAX_AGE_HOURS * 3600


def _mem_get(key: str) -> Any | None:
    entry = _MEM_CACHE.get(key)
    if entry is None:
        return None
    ts, data = entry
    if _time.time() - ts > _CACHE_TTL:
        del _MEM_CACHE[key]
        return None
    return data


def _mem_set(key: str, data: Any) -> None:
    _MEM_CACHE[key] = (_time.time(), data)


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _clean(df: pd.DataFrame) -> list[dict]:
    """Replace non-JSON-serialisable values and convert to records."""
    df = df.replace({np.nan: None, np.inf: None, -np.inf: None})
    return df.to_dict(orient="records")


def _round_floats(df: pd.DataFrame, decimals: int = 3) -> pd.DataFrame:
    float_cols = df.select_dtypes(include=[float]).columns
    df[float_cols] = df[float_cols].round(decimals)
    return df


def _validate_timeframe(timeframe: str) -> None:
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid timeframe '{timeframe}'. Valid options: {VALID_TIMEFRAMES}",
        )


def _get_batting_df(season: int, timeframe: str) -> pd.DataFrame:
    if timeframe == "season":
        return fetch_batting(season)
    window = TIMEFRAME_WINDOWS[timeframe]
    end = datetime.strptime(SEASON_END, "%Y-%m-%d")
    start = end - timedelta(days=window["days"])
    return fetch_batting_range(
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        window["min_ab"],
    )


def _get_pitching_df(season: int, timeframe: str) -> pd.DataFrame:
    if timeframe == "season":
        return fetch_pitching(season)
    window = TIMEFRAME_WINDOWS[timeframe]
    end = datetime.strptime(SEASON_END, "%Y-%m-%d")
    start = end - timedelta(days=window["days"])
    return fetch_pitching_range(
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        window["min_ip"],
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "cached_keys": list(_MEM_CACHE.keys())}


@app.get("/api/hitters", tags=["rankings"])
def get_hitters(
    season: int = Query(2025, ge=2000, le=2030),
    limit: int = Query(100, ge=1, le=500),
    timeframe: str = Query("season", description="season | last60 | last30 | last14"),
):
    """
    Top hitters ranked by total z-score across R, HR, RBI, SB, AVG.
    AVG is weighted by AB (contribution-based z-score).
    """
    _validate_timeframe(timeframe)
    cache_key = f"hitters:{season}:{timeframe}"
    if cached := _mem_get(cache_key):
        return cached

    try:
        df = _get_batting_df(season, timeframe)
        df = compute_hitter_zscores(df)
        df = (
            df.sort_values("total_z", ascending=False)
            .head(limit)
            .reset_index(drop=True)
        )
        df.insert(0, "rank", range(1, len(df) + 1))
        df = _round_floats(df)
        result = {
            "players": _clean(df),
            "count": len(df),
            "season": season,
            "timeframe": timeframe,
        }
        _mem_set(cache_key, result)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in /api/hitters")
        raise HTTPException(status_code=500, detail="Failed to compute hitter rankings.")


@app.get("/api/pitchers", tags=["rankings"])
def get_pitchers(
    season: int = Query(2025, ge=2000, le=2030),
    limit: int = Query(100, ge=1, le=500),
    timeframe: str = Query("season", description="season | last60 | last30 | last14"),
):
    """
    Top pitchers ranked by total z-score across K, W, SV, HLD, ERA, WHIP.
    ERA and WHIP are weighted by IP. HLD excluded for date-range timeframes.
    """
    _validate_timeframe(timeframe)
    cache_key = f"pitchers:{season}:{timeframe}"
    if cached := _mem_get(cache_key):
        return cached

    try:
        hld_available = timeframe == "season"
        df = _get_pitching_df(season, timeframe)
        df = compute_pitcher_zscores(df, include_hld=hld_available)
        df = (
            df.sort_values("total_z", ascending=False)
            .head(limit)
            .reset_index(drop=True)
        )
        df.insert(0, "rank", range(1, len(df) + 1))
        df = df.rename(columns={"SO": "K", "zSO": "zK"})
        df = _round_floats(df)
        result = {
            "players": _clean(df),
            "count": len(df),
            "season": season,
            "timeframe": timeframe,
            "hld_available": hld_available,
        }
        _mem_set(cache_key, result)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in /api/pitchers")
        raise HTTPException(status_code=500, detail="Failed to compute pitcher rankings.")


@app.get("/api/teams", tags=["roster"])
def get_teams(season: int = Query(2025, ge=2000, le=2030)):
    """Return sorted list of all team abbreviations present in the player pool."""
    cache_key = f"teams:{season}"
    if cached := _mem_get(cache_key):
        return cached

    try:
        batting_df = fetch_batting(season)
        pitching_df = fetch_pitching(season)
        all_teams = sorted(
            {t for t in batting_df["Team"].dropna().tolist()
                + pitching_df["Team"].dropna().tolist()
             if t and str(t).strip()}
        )
        result = {"teams": all_teams, "season": season}
        _mem_set(cache_key, result)
        return result
    except Exception:
        logger.exception("Error in /api/teams")
        raise HTTPException(status_code=500, detail="Failed to get teams.")


@app.get("/api/players/grouped", tags=["roster"])
def get_players_grouped(
    season: int = Query(2025, ge=2000, le=2030),
    timeframe: str = Query("season", description="season | last60 | last30 | last14"),
):
    """
    All players with z-scores grouped by team.
    Used by the Team Builder and Trade Analyzer pages.
    Returns every qualifying player (no top-N cap).
    """
    _validate_timeframe(timeframe)
    cache_key = f"grouped:{season}:{timeframe}"
    if cached := _mem_get(cache_key):
        return cached

    try:
        hld_available = timeframe == "season"

        batting_df = _get_batting_df(season, timeframe)
        batting_df = compute_hitter_zscores(batting_df)
        batting_df = _round_floats(batting_df)
        batting_df["rank"] = (
            batting_df["total_z"]
            .rank(ascending=False, method="min")
            .astype(int)
        )

        pitching_df = _get_pitching_df(season, timeframe)
        pitching_df = compute_pitcher_zscores(pitching_df, include_hld=hld_available)
        pitching_df = pitching_df.rename(columns={"SO": "K", "zSO": "zK"})
        pitching_df = _round_floats(pitching_df)
        pitching_df["rank"] = (
            pitching_df["total_z"]
            .rank(ascending=False, method="min")
            .astype(int)
        )

        def group_by_team(df: pd.DataFrame) -> dict[str, list]:
            grouped: dict[str, list] = {}
            for team, grp in df.groupby("Team", sort=True):
                team_str = str(team).strip()
                if team_str:
                    grouped[team_str] = _clean(
                        grp.sort_values("total_z", ascending=False)
                    )
            return grouped

        result = {
            "hitters": group_by_team(batting_df),
            "pitchers": group_by_team(pitching_df),
            "season": season,
            "timeframe": timeframe,
            "hld_available": hld_available,
        }
        _mem_set(cache_key, result)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in /api/players/grouped")
        raise HTTPException(status_code=500, detail="Failed to get grouped players.")

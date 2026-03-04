"""
Fantasy Baseball Z-Score API
Run with:  uvicorn main:app --reload --port 8000
"""

import logging

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from data_fetcher import fetch_batting, fetch_pitching
from zscore import compute_hitter_zscores, compute_pitcher_zscores

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fantasy Baseball Z-Score API",
    description="2025 MLB fantasy rankings powered by FanGraphs / pybaseball",
    version="1.0.0",
)

# Allow requests from the Next.js dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _clean(df: pd.DataFrame) -> list[dict]:
    """Replace non-JSON-serialisable values and convert to records."""
    df = df.replace({np.nan: None, np.inf: None, -np.inf: None})
    return df.to_dict(orient="records")


def _round_floats(df: pd.DataFrame, decimals: int = 3) -> pd.DataFrame:
    float_cols = df.select_dtypes(include=[float]).columns
    df[float_cols] = df[float_cols].round(decimals)
    return df


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/api/hitters", tags=["rankings"])
def get_hitters(
    season: int = Query(2025, ge=2000, le=2030, description="MLB season year"),
    limit: int = Query(100, ge=1, le=500, description="Max players to return"),
):
    """
    Returns top hitters ranked by total z-score across R, HR, RBI, SB, AVG.
    AVG is weighted by AB (contribution-based z-score).
    """
    try:
        df = fetch_batting(season)
        df = compute_hitter_zscores(df)
        df = (
            df.sort_values("total_z", ascending=False)
            .head(limit)
            .reset_index(drop=True)
        )
        df.insert(0, "rank", range(1, len(df) + 1))
        df = _round_floats(df)
        return {"players": _clean(df), "count": len(df), "season": season}
    except Exception:
        logger.exception("Error in /api/hitters")
        raise HTTPException(
            status_code=500,
            detail="Failed to compute hitter rankings. Check backend logs.",
        )


@app.get("/api/pitchers", tags=["rankings"])
def get_pitchers(
    season: int = Query(2025, ge=2000, le=2030, description="MLB season year"),
    limit: int = Query(100, ge=1, le=500, description="Max players to return"),
):
    """
    Returns top pitchers ranked by total z-score across K, W, SV, HLD, ERA, WHIP.
    ERA and WHIP are weighted by IP (contribution-based z-score).
    """
    try:
        df = fetch_pitching(season)
        df = compute_pitcher_zscores(df)
        df = (
            df.sort_values("total_z", ascending=False)
            .head(limit)
            .reset_index(drop=True)
        )
        df.insert(0, "rank", range(1, len(df) + 1))
        # Rename SO → K and zSO → zK for display
        df = df.rename(columns={"SO": "K", "zSO": "zK"})
        df = _round_floats(df)
        return {"players": _clean(df), "count": len(df), "season": season}
    except Exception:
        logger.exception("Error in /api/pitchers")
        raise HTTPException(
            status_code=500,
            detail="Failed to compute pitcher rankings. Check backend logs.",
        )

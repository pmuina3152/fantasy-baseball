"""
Pydantic response models for the Fantasy Baseball API.
Used for documentation and IDE type hints.
"""

from typing import Optional
from pydantic import BaseModel


class HitterRecord(BaseModel):
    rank: int
    Name: str
    Team: Optional[str] = None
    AB: float
    R: float
    HR: float
    RBI: float
    SB: float
    AVG: float
    zR: float
    zHR: float
    zRBI: float
    zSB: float
    zAVG: float
    total_z: float
    score_0_100: float


class PitcherRecord(BaseModel):
    rank: int
    Name: str
    Team: Optional[str] = None
    IP: float
    K: float
    W: float
    SV: float
    HLD: float = 0.0
    ERA: float
    WHIP: float
    zK: float
    zW: float
    zSV: float
    zHLD: float = 0.0
    zERA: float
    zWHIP: float
    total_z: float
    score_0_100: float


class HitterRankingsResponse(BaseModel):
    players: list[HitterRecord]
    count: int
    season: int
    timeframe: str


class PitcherRankingsResponse(BaseModel):
    players: list[PitcherRecord]
    count: int
    season: int
    timeframe: str
    hld_available: bool


class TeamsResponse(BaseModel):
    teams: list[str]
    season: int


class GroupedPlayersResponse(BaseModel):
    hitters: dict[str, list[HitterRecord]]
    pitchers: dict[str, list[PitcherRecord]]
    season: int
    timeframe: str
    hld_available: bool

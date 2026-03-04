export type PlayerType = "hitters" | "pitchers";

export interface HitterRow {
  rank: number;
  Name: string;
  Team: string | null;
  AB: number;
  R: number;
  HR: number;
  RBI: number;
  SB: number;
  AVG: number;
  zR: number;
  zHR: number;
  zRBI: number;
  zSB: number;
  zAVG: number;
  total_z: number;
  score_0_100: number;
}

export interface PitcherRow {
  rank: number;
  Name: string;
  Team: string | null;
  IP: number;
  K: number;
  W: number;
  SV: number;
  HLD: number;
  ERA: number;
  WHIP: number;
  zK: number;
  zW: number;
  zSV: number;
  zHLD: number;
  zERA: number;
  zWHIP: number;
  total_z: number;
  score_0_100: number;
}

export interface ApiResponse<T> {
  players: T[];
  count: number;
  season: number;
}

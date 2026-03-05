// ── Core domain types ─────────────────────────────────────────────────────────

export type PlayerType = "hitters" | "pitchers";
export type DisplayMode = "zscore" | "raw";
export type Timeframe = "season" | "last60g" | "last25g" | "last5g";

// Stat keys — used for include/exclude filtering
export type HitterStatKey = "zR" | "zHR" | "zRBI" | "zSB" | "zAVG";
export type PitcherStatKey = "zK" | "zW" | "zSV" | "zHLD" | "zERA" | "zWHIP";
export type StatKey = HitterStatKey | PitcherStatKey;

// Human-readable labels for each stat key
export const HITTER_STAT_LABELS: Record<HitterStatKey, string> = {
  zR:   "R",
  zHR:  "HR",
  zRBI: "RBI",
  zSB:  "SB",
  zAVG: "AVG",
};
export const PITCHER_STAT_LABELS: Record<PitcherStatKey, string> = {
  zK:    "K",
  zW:    "W",
  zSV:   "SV",
  zHLD:  "HLD",
  zERA:  "ERA",
  zWHIP: "WHIP",
};

export const ALL_HITTER_STAT_KEYS: HitterStatKey[] = ["zR", "zHR", "zRBI", "zSB", "zAVG"];
export const ALL_PITCHER_STAT_KEYS: PitcherStatKey[] = ["zK", "zW", "zSV", "zHLD", "zERA", "zWHIP"];

export const TIMEFRAME_LABELS: Record<Timeframe, string> = {
  season:  "Full Season",
  last60g: "Last 60 Games",
  last25g: "Last 25 Games",
  last5g:  "Last 5 Games",
};

// ── API row shapes ─────────────────────────────────────────────────────────────

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

export type PlayerRow = HitterRow | PitcherRow;

// ── API response shapes ────────────────────────────────────────────────────────

export interface RankingsResponse<T> {
  players: T[];
  count: number;
  season: number;
  timeframe: string;
  hld_available?: boolean;
}

export interface TeamsResponse {
  teams: string[];
  season: number;
}

export interface GroupedPlayersResponse {
  hitters: Record<string, HitterRow[]>;
  pitchers: Record<string, PitcherRow[]>;
  season: number;
  timeframe: string;
  hld_available: boolean;
}

// ── Team builder types ─────────────────────────────────────────────────────────

export type RosterSlotType = "hitter" | "pitcher" | "il";

export interface RosterSlot {
  slotType: RosterSlotType;
  slotIndex: number;
  player: HitterRow | PitcherRow | null;
}

export interface MyTeam {
  hitters: (HitterRow | null)[];   // unlimited
  pitchers: (PitcherRow | null)[]; // unlimited
  il: (PlayerRow | null)[];        // max 3 slots
}

// ── Trade analyzer types ───────────────────────────────────────────────────────

export interface StatDelta {
  stat: string;
  label: string;
  sideA: number;
  sideB: number;
  delta: number; // sideB - sideA  (positive = gaining, from Side A's perspective)
}

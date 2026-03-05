import type {
  HitterRow,
  HitterStatKey,
  PitcherRow,
  PitcherStatKey,
  PlayerRow,
  StatDelta,
} from "./types";


// ── Z-score recomputation ─────────────────────────────────────────────────────

/**
 * Recompute a hitter's total z-score using only the included stat keys.
 * Used for client-side stat filtering (checked stats).
 */
export function recomputeHitterZ(
  player: HitterRow,
  included: Set<HitterStatKey>,
): number {
  const keys: HitterStatKey[] = ["zR", "zHR", "zRBI", "zSB", "zAVG"];
  return keys
    .filter((k) => included.has(k))
    .reduce((sum, k) => sum + (player[k] ?? 0), 0);
}

/**
 * Recompute a pitcher's total z-score using only the included stat keys.
 */
export function recomputePitcherZ(
  player: PitcherRow,
  included: Set<PitcherStatKey>,
): number {
  const keys: PitcherStatKey[] = ["zK", "zW", "zSV", "zHLD", "zERA", "zWHIP"];
  return keys
    .filter((k) => included.has(k))
    .reduce((sum, k) => sum + (player[k] ?? 0), 0);
}

/**
 * Re-normalise total_z values to 0–100 over the visible player pool.
 * Returns a new array with score_0_100 replaced.
 */
export function renormalise<T extends { total_z: number; score_0_100: number }>(
  players: T[],
): T[] {
  if (players.length === 0) return players;
  const vals = players.map((p) => p.total_z);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min;
  return players.map((p) => ({
    ...p,
    score_0_100: range === 0 ? 50 : (100 * (p.total_z - min)) / range,
  }));
}

// ── Stat aggregation ──────────────────────────────────────────────────────────

/** Sum a single numeric field across an array of players. */
function sumField(players: PlayerRow[], field: string): number {
  return players.reduce((acc, p) => acc + (((p as any)[field] as number) ?? 0), 0);
}

/** Round to 3 decimal places. */
function r3(n: number) {
  return Math.round(n * 1000) / 1000;
}

/**
 * Compute per-stat totals (raw + z-score) for a mixed list of hitters.
 */
export function sumHitterStats(players: HitterRow[]) {
  if (players.length === 0) return null;
  return {
    R:    r3(sumField(players, "R")),
    HR:   r3(sumField(players, "HR")),
    RBI:  r3(sumField(players, "RBI")),
    SB:   r3(sumField(players, "SB")),
    AVG:  r3(sumField(players, "AVG") / players.length), // mean
    zR:   r3(sumField(players, "zR")),
    zHR:  r3(sumField(players, "zHR")),
    zRBI: r3(sumField(players, "zRBI")),
    zSB:  r3(sumField(players, "zSB")),
    zAVG: r3(sumField(players, "zAVG")),
    total_z: r3(sumField(players, "total_z")),
  };
}

export function sumPitcherStats(players: PitcherRow[]) {
  if (players.length === 0) return null;
  return {
    IP:   r3(sumField(players, "IP")),
    K:    r3(sumField(players, "K")),
    W:    r3(sumField(players, "W")),
    SV:   r3(sumField(players, "SV")),
    HLD:  r3(sumField(players, "HLD")),
    ERA:  r3(sumField(players, "ERA") / players.length), // mean
    WHIP: r3(sumField(players, "WHIP") / players.length),
    zK:    r3(sumField(players, "zK")),
    zW:    r3(sumField(players, "zW")),
    zSV:   r3(sumField(players, "zSV")),
    zHLD:  r3(sumField(players, "zHLD")),
    zERA:  r3(sumField(players, "zERA")),
    zWHIP: r3(sumField(players, "zWHIP")),
    total_z: r3(sumField(players, "total_z")),
  };
}

// ── Trade delta ────────────────────────────────────────────────────────────────

/**
 * Compute per-stat deltas between two player groups.
 * From Team A's perspective:
 *   - sideA = players being given away
 *   - sideB = players being received
 *   - delta = sideB_total - sideA_total  (positive = gaining)
 */
export function deltaHitterStats(
  sideA: HitterRow[],
  sideB: HitterRow[],
): StatDelta[] {
  const a = sumHitterStats(sideA);
  const b = sumHitterStats(sideB);
  if (!a || !b) return [];

  const entries: [HitterStatKey, string][] = [
    ["zR",   "R"],
    ["zHR",  "HR"],
    ["zRBI", "RBI"],
    ["zSB",  "SB"],
    ["zAVG", "AVG"],
  ];

  return entries.map(([key, label]) => ({
    stat: key,
    label,
    sideA: a[key],
    sideB: b[key],
    delta: r3(b[key] - a[key]),
  }));
}

export function deltaPitcherStats(
  sideA: PitcherRow[],
  sideB: PitcherRow[],
): StatDelta[] {
  const a = sumPitcherStats(sideA);
  const b = sumPitcherStats(sideB);
  if (!a || !b) return [];

  const entries: [PitcherStatKey, string][] = [
    ["zK",    "K"],
    ["zW",    "W"],
    ["zSV",   "SV"],
    ["zHLD",  "HLD"],
    ["zERA",  "ERA"],
    ["zWHIP", "WHIP"],
  ];

  return entries.map(([key, label]) => ({
    stat: key,
    label,
    sideA: a[key],
    sideB: b[key],
    delta: r3(b[key] - a[key]),
  }));
}

/** Combine hitter + pitcher deltas for a mixed-group trade. */
export function deltaMixedStats(
  sideA: PlayerRow[],
  sideB: PlayerRow[],
): StatDelta[] {
  const aHitters = sideA.filter((p) => "AVG" in p) as HitterRow[];
  const bHitters = sideB.filter((p) => "AVG" in p) as HitterRow[];
  const aPitchers = sideA.filter((p) => "ERA" in p) as PitcherRow[];
  const bPitchers = sideB.filter((p) => "ERA" in p) as PitcherRow[];

  const hDeltas = aHitters.length > 0 || bHitters.length > 0
    ? deltaHitterStats(aHitters, bHitters)
    : [];
  const pDeltas = aPitchers.length > 0 || bPitchers.length > 0
    ? deltaPitcherStats(aPitchers, bPitchers)
    : [];

  return [...hDeltas, ...pDeltas];
}

/** Identify if a row is a hitter. */
export function isHitter(player: PlayerRow): player is HitterRow {
  return "AVG" in player;
}

// ── Trade result helpers ───────────────────────────────────────────────────────

export interface TradeResult {
  /** Stats where this team comes out ahead */
  gained: StatDelta[];
  /** Stats where this team loses ground */
  lost: StatDelta[];
  /** Net z-score change for this team */
  totalZ: number;
}

/**
 * Compute a trade result from one team's perspective.
 * Deltas are always stored as (sideB − sideA), which represents Team A's gain.
 * For Team B we invert the sign.
 */
export function computeTradeResult(
  deltas: StatDelta[],
  perspective: "A" | "B",
): TradeResult {
  const sign = perspective === "A" ? 1 : -1;
  const adjusted = deltas.map((d) => ({
    ...d,
    delta: r3(d.delta * sign),
    sideA: perspective === "A" ? d.sideA : d.sideB,
    sideB: perspective === "A" ? d.sideB : d.sideA,
  }));
  return {
    gained: adjusted.filter((d) => d.delta > 0.001),
    lost: adjusted.filter((d) => d.delta < -0.001),
    totalZ: r3(adjusted.reduce((sum, d) => sum + d.delta, 0)),
  };
}

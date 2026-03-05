import type {
  GroupedPlayersResponse,
  HitterRow,
  PitcherRow,
  RankingsResponse,
  TeamsResponse,
  Timeframe,
} from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Client-side in-memory cache ───────────────────────────────────────────────
// Prevents duplicate network requests when switching pages or toggling stats.
// TTL matches the backend 12-hour cache so results stay consistent.

const CLIENT_CACHE_TTL_MS = 12 * 60 * 60 * 1000; // 12 hours

interface CacheEntry {
  ts: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
}

const _apiCache = new Map<string, CacheEntry>();

function cacheGet<T>(key: string): T | null {
  const entry = _apiCache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.ts > CLIENT_CACHE_TTL_MS) {
    _apiCache.delete(key);
    return null;
  }
  return entry.data as T;
}

function cacheSet(key: string, data: unknown): void {
  _apiCache.set(key, { ts: Date.now(), data });
}

// ── Core fetch helper ─────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const cached = cacheGet<T>(path);
  if (cached !== null) return cached;

  const res = await fetch(`${BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API error ${res.status}: ${text}`);
  }
  const data = (await res.json()) as T;
  cacheSet(path, data);
  return data;
}

// ── Rankings ──────────────────────────────────────────────────────────────────

export async function fetchHitters(
  season = 2025,
  limit = 100,
  timeframe: Timeframe = "season",
): Promise<HitterRow[]> {
  const data = await get<RankingsResponse<HitterRow>>(
    `/api/hitters?season=${season}&limit=${limit}&timeframe=${timeframe}`,
  );
  return data.players;
}

export async function fetchPitchers(
  season = 2025,
  limit = 100,
  timeframe: Timeframe = "season",
): Promise<RankingsResponse<PitcherRow>> {
  return get<RankingsResponse<PitcherRow>>(
    `/api/pitchers?season=${season}&limit=${limit}&timeframe=${timeframe}`,
  );
}

// ── Roster helpers ────────────────────────────────────────────────────────────

export async function fetchTeams(season = 2025): Promise<string[]> {
  const data = await get<TeamsResponse>(`/api/teams?season=${season}`);
  return data.teams;
}

export async function fetchGroupedPlayers(
  season = 2025,
  timeframe: Timeframe = "season",
): Promise<GroupedPlayersResponse> {
  return get<GroupedPlayersResponse>(
    `/api/players/grouped?season=${season}&timeframe=${timeframe}`,
  );
}

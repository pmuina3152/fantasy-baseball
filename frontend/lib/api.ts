import type { ApiResponse, HitterRow, PitcherRow } from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    // Disable Next.js static cache so we always hit the live FastAPI server
    cache: "no-store",
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API error ${res.status}: ${text}`);
  }

  return res.json() as Promise<T>;
}

export async function fetchHitters(
  season = 2025,
  limit = 100
): Promise<HitterRow[]> {
  const data = await get<ApiResponse<HitterRow>>(
    `/api/hitters?season=${season}&limit=${limit}`
  );
  return data.players;
}

export async function fetchPitchers(
  season = 2025,
  limit = 100
): Promise<PitcherRow[]> {
  const data = await get<ApiResponse<PitcherRow>>(
    `/api/pitchers?season=${season}&limit=${limit}`
  );
  return data.players;
}

/**
 * localStorage persistence helpers for the Team Builder roster.
 */

import type { MyTeam, HitterRow, PitcherRow, PlayerRow } from "./types";

const TEAM_KEY = "fantasy-baseball-my-team";

export function emptyTeam(): MyTeam {
  return {
    hitters:  [],
    pitchers: [],
    il:       Array(3).fill(null),
  };
}

export function loadTeam(): MyTeam {
  if (typeof window === "undefined") return emptyTeam();
  try {
    const raw = localStorage.getItem(TEAM_KEY);
    if (!raw) return emptyTeam();
    return JSON.parse(raw) as MyTeam;
  } catch {
    return emptyTeam();
  }
}

export function saveTeam(team: MyTeam): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(TEAM_KEY, JSON.stringify(team));
  } catch {
    // localStorage might be unavailable (private mode quota, etc.)
  }
}

export function clearTeam(): MyTeam {
  if (typeof window !== "undefined") {
    localStorage.removeItem(TEAM_KEY);
  }
  return emptyTeam();
}

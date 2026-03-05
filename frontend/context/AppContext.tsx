"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  ALL_HITTER_STAT_KEYS,
  ALL_PITCHER_STAT_KEYS,
  type DisplayMode,
  type HitterStatKey,
  type PitcherStatKey,
  type Timeframe,
} from "@/lib/types";

// ── Context shape ─────────────────────────────────────────────────────────────

interface AppContextValue {
  // Display mode: show z-scores or raw stats
  displayMode: DisplayMode;
  setDisplayMode: (m: DisplayMode) => void;

  // Timeframe selector
  timeframe: Timeframe;
  setTimeframe: (t: Timeframe) => void;

  // Included stat keys (checked = included in total_z)
  includedHitterStats: Set<HitterStatKey>;
  includedPitcherStats: Set<PitcherStatKey>;
  toggleHitterStat: (key: HitterStatKey) => void;
  togglePitcherStat: (key: PitcherStatKey) => void;
  resetStats: () => void;
}

const AppContext = createContext<AppContextValue | null>(null);

const STORAGE_KEY = "fantasy-baseball-app-prefs";

interface Prefs {
  displayMode: DisplayMode;
  timeframe: Timeframe;
  includedHitterStats: HitterStatKey[];
  includedPitcherStats: PitcherStatKey[];
}

function loadPrefs(): Prefs {
  if (typeof window === "undefined") {
    return {
      displayMode: "zscore",
      timeframe: "season",
      includedHitterStats: [...ALL_HITTER_STAT_KEYS],
      includedPitcherStats: [...ALL_PITCHER_STAT_KEYS],
    };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Prefs;
      // Guard against old timeframe keys stored from previous version
      const validTFs: Timeframe[] = ["season", "last60g", "last25g", "last5g"];
      if (!validTFs.includes(parsed.timeframe)) parsed.timeframe = "season";
      return parsed;
    }
  } catch {
    // ignore
  }
  return {
    displayMode: "zscore",
    timeframe: "season",
    includedHitterStats: [...ALL_HITTER_STAT_KEYS],
    includedPitcherStats: [...ALL_PITCHER_STAT_KEYS],
  };
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [displayMode, setDisplayModeState] = useState<DisplayMode>("zscore");
  const [timeframe, setTimeframeState] = useState<Timeframe>("season");
  const [includedHitterStats, setIncludedHitterStats] = useState<Set<HitterStatKey>>(
    new Set(ALL_HITTER_STAT_KEYS),
  );
  const [includedPitcherStats, setIncludedPitcherStats] = useState<Set<PitcherStatKey>>(
    new Set(ALL_PITCHER_STAT_KEYS),
  );
  const [hydrated, setHydrated] = useState(false);

  // Hydrate from localStorage after mount
  useEffect(() => {
    const prefs = loadPrefs();
    setDisplayModeState(prefs.displayMode);
    setTimeframeState(prefs.timeframe);
    setIncludedHitterStats(new Set(prefs.includedHitterStats));
    setIncludedPitcherStats(new Set(prefs.includedPitcherStats));
    setHydrated(true);
  }, []);

  // Persist to localStorage whenever prefs change
  useEffect(() => {
    if (!hydrated) return;
    try {
      const prefs: Prefs = {
        displayMode,
        timeframe,
        includedHitterStats: [...includedHitterStats],
        includedPitcherStats: [...includedPitcherStats],
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      // ignore
    }
  }, [displayMode, timeframe, includedHitterStats, includedPitcherStats, hydrated]);

  const setDisplayMode = useCallback((m: DisplayMode) => setDisplayModeState(m), []);
  const setTimeframe = useCallback((t: Timeframe) => setTimeframeState(t), []);

  const toggleHitterStat = useCallback((key: HitterStatKey) => {
    setIncludedHitterStats((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size === 1) return prev; // keep at least one stat
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const togglePitcherStat = useCallback((key: PitcherStatKey) => {
    setIncludedPitcherStats((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size === 1) return prev;
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const resetStats = useCallback(() => {
    setIncludedHitterStats(new Set(ALL_HITTER_STAT_KEYS));
    setIncludedPitcherStats(new Set(ALL_PITCHER_STAT_KEYS));
  }, []);

  return (
    <AppContext.Provider
      value={{
        displayMode,
        setDisplayMode,
        timeframe,
        setTimeframe,
        includedHitterStats,
        includedPitcherStats,
        toggleHitterStat,
        togglePitcherStat,
        resetStats,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside <AppProvider>");
  return ctx;
}

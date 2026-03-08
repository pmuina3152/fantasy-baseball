"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Toggle from "@/components/Toggle";
import PlayerTable from "@/components/PlayerTable";
import StatControls from "@/components/StatControls";
import TimeframeSelector from "@/components/TimeframeSelector";
import { fetchHitters, fetchPitchers, fetchProjectedHitters } from "@/lib/api";
import { useApp } from "@/context/AppContext";
import type { DataMode, HitterRow, PitcherRow, PlayerType } from "@/lib/types";

// ── Data-mode segmented control ───────────────────────────────────────────────

interface DataModePillProps {
  value: DataMode;
  onChange: (v: DataMode) => void;
}

function DataModePill({ value, onChange }: DataModePillProps) {
  const opts: { id: DataMode; label: string }[] = [
    { id: "actual",     label: "2025 Stats" },
    { id: "projection", label: "2026 Projections" },
  ];
  return (
    <div className="inline-flex items-center rounded-full bg-gray-800 p-0.5 gap-0.5">
      {opts.map((opt) => (
        <button
          key={opt.id}
          onClick={() => onChange(opt.id)}
          className={[
            "px-3 py-1 text-xs font-medium rounded-full transition-colors",
            value === opt.id
              ? "bg-blue-600 text-white shadow"
              : "text-gray-400 hover:text-gray-200",
          ].join(" ")}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RankingsPage() {
  const { timeframe, displayMode, includedHitterStats, includedPitcherStats } = useApp();

  const [dataMode, setDataMode]     = useState<DataMode>("actual");
  const [playerType, setPlayerType] = useState<PlayerType>("hitters");
  const [hitters, setHitters]       = useState<HitterRow[]>([]);
  const [projectedHitters, setProjectedHitters] = useState<HitterRow[]>([]);
  const [pitchers, setPitchers]     = useState<PitcherRow[]>([]);
  const [hldAvailable, setHldAvailable] = useState(true);
  // "refreshing" = new data is loading but we still show the previous table
  const [loading, setLoading]       = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError]           = useState<string | null>(null);

  // Which fetch keys have already been loaded into state
  const fetched = useRef<Set<string>>(new Set());

  const load = useCallback(
    async (
      type: PlayerType,
      tf: string,
      dm: DataMode,
      keepStale = false,
    ) => {
      const key = `${type}:${tf}:${dm}`;
      if (fetched.current.has(key)) return;

      const hasData =
        dm === "projection"
          ? projectedHitters.length > 0
          : type === "hitters"
          ? hitters.length > 0
          : pitchers.length > 0;

      if (keepStale && hasData) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError(null);

      try {
        if (dm === "projection") {
          // Only hitters are projected — fetch all qualifying players
          const data = await fetchProjectedHitters(500);
          setProjectedHitters(data);
        } else if (type === "hitters") {
          // Raise limit to 500 to show all qualifying hitters (no top-100 cap)
          const data = await fetchHitters(2025, 500, tf as import("@/lib/types").Timeframe);
          setHitters(data);
        } else {
          const json = await fetchPitchers(2025, 500, tf as import("@/lib/types").Timeframe);
          setPitchers(json.players);
          setHldAvailable(json.hld_available ?? true);
        }
        fetched.current.add(key);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error occurred.");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // When timeframe changes in actual mode, invalidate cache but keep visible
  useEffect(() => {
    if (dataMode === "actual") {
      fetched.current.clear();
      load(playerType, timeframe, "actual", true);
    }
  }, [timeframe]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load on player-type switch
  useEffect(() => {
    load(playerType, timeframe, dataMode);
  }, [playerType, load, timeframe]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load when data mode changes
  useEffect(() => {
    if (dataMode === "projection" && projectedHitters.length === 0) {
      load("hitters", timeframe, "projection");
    } else if (dataMode === "actual") {
      load(playerType, timeframe, "actual");
    }
  }, [dataMode]); // eslint-disable-line react-hooks/exhaustive-deps

  const retry = () => {
    fetched.current.delete(`${playerType}:${timeframe}:${dataMode}`);
    setError(null);
    load(playerType, timeframe, dataMode);
  };

  // Determine which player array to display
  const currentPlayers: HitterRow[] | PitcherRow[] =
    dataMode === "projection"
      ? projectedHitters
      : playerType === "hitters"
      ? hitters
      : pitchers;

  const showTable = !loading && !error && currentPlayers.length > 0;

  // Subtitle
  const subtitle =
    dataMode === "projection"
      ? "2026 projected stats · skill model (2023–2025)"
      : `All qualifying players ranked by total fantasy z-score${
          timeframe !== "season" ? " · HLD excluded for game-window views" : ""
        }`;

  return (
    <main className="min-h-screen bg-gray-950">
      {/* Page header */}
      <div className="border-b border-gray-800 bg-gray-900/80">
        <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 py-4 space-y-3">
          {/* Title row */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h1 className="text-xl font-bold text-white">
                {dataMode === "projection" ? "2026 Projected Rankings" : "2025 Player Rankings"}
              </h1>
              <p className="text-xs text-gray-500 mt-0.5">
                {subtitle}
                {dataMode === "projection" && (
                  <span className="ml-1 text-blue-400">· weighted 50/30/20</span>
                )}
              </p>
            </div>

            {/* Right side: data-mode pill + hitter/pitcher toggle */}
            <div className="flex items-center gap-3 flex-wrap">
              <DataModePill value={dataMode} onChange={setDataMode} />
              {/* Hide hitter/pitcher toggle in projection mode — only hitters are projected */}
              {dataMode === "actual" && (
                <Toggle value={playerType} onChange={setPlayerType} />
              )}
            </div>
          </div>

          {/* Controls row — hide timeframe selector in projection mode */}
          {dataMode === "actual" && (
            <div className="flex flex-wrap items-center gap-3">
              <TimeframeSelector />
              <div className="w-px h-4 bg-gray-700 hidden sm:block" />
              <StatControls playerType={playerType} />
            </div>
          )}

          {/* Stat controls for projection mode (z-score/raw toggle still useful) */}
          {dataMode === "projection" && (
            <div className="flex flex-wrap items-center gap-3">
              <StatControls playerType="hitters" />
            </div>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 py-6">
        <div className="flex items-center justify-between mb-4 text-xs text-gray-500">
          <span className="flex items-center gap-2">
            {currentPlayers.length > 0
              ? `${currentPlayers.length} ${dataMode === "projection" ? "projected hitters" : playerType} · sorted by ${dataMode === "projection" ? "projected z-score" : "adjusted z-score"}`
              : `Loading ${dataMode === "projection" ? "projections" : playerType}…`}
            {refreshing && (
              <span className="flex items-center gap-1 text-blue-400">
                <span className="w-3 h-3 rounded-full border border-blue-400 border-t-transparent animate-spin inline-block" />
                refreshing…
              </span>
            )}
          </span>
          <span className="hidden sm:inline">
            {dataMode === "projection"
              ? "PA ≥ 100 in 2025 · projected_PA in AB column"
              : "AB ≥ 100 / 50 / 20 / 4 \u00a0·\u00a0 IP ≥ 20 / 12 / 7 / 1.5"}
          </span>
        </div>

        {/* Full-page spinner — only shown on first load when there is no data yet */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-40 gap-5">
            <div className="w-12 h-12 rounded-full border-[3px] border-blue-600 border-t-transparent animate-spin" />
            <div className="text-center space-y-1">
              <p className="text-gray-200 font-medium">
                {dataMode === "projection"
                  ? "Building 2026 projections…"
                  : `Loading ${playerType}…`}
              </p>
              <p className="text-gray-500 text-xs">
                {dataMode === "projection"
                  ? "First load fetches 3 seasons of skill data — may take 30–90 s."
                  : "First load pulls live data — may take 15–45 s."}
              </p>
            </div>
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="max-w-2xl mx-auto mt-8 bg-red-950/40 border border-red-800 rounded-2xl p-6 space-y-3">
            <h2 className="text-red-300 font-semibold">Failed to load data</h2>
            <pre className="text-red-400 text-xs font-mono whitespace-pre-wrap break-all bg-black/30 rounded-lg p-3">
              {error}
            </pre>
            <p className="text-gray-500 text-xs">
              Ensure the backend is running:{" "}
              <code className="text-gray-300 bg-gray-800 px-1.5 py-0.5 rounded">
                uvicorn main:app --reload --port 8000
              </code>
            </p>
            <button
              onClick={retry}
              className="px-4 py-2 bg-red-800 hover:bg-red-700 text-white text-sm rounded-lg transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {/* Table — shown even while refreshing (stale data stays visible) */}
        {showTable && (
          <div className={refreshing ? "opacity-60 pointer-events-none transition-opacity" : "transition-opacity"}>
            {dataMode === "projection" || playerType === "hitters" ? (
              <PlayerTable
                players={dataMode === "projection" ? projectedHitters : hitters}
                type="hitters"
                displayMode={displayMode}
                includedStats={includedHitterStats}
              />
            ) : (
              <PlayerTable
                players={pitchers}
                type="pitchers"
                displayMode={displayMode}
                includedStats={includedPitcherStats}
                hldAvailable={hldAvailable}
              />
            )}
          </div>
        )}
      </div>
    </main>
  );
}

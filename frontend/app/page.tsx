"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Toggle from "@/components/Toggle";
import PlayerTable from "@/components/PlayerTable";
import { fetchHitters, fetchPitchers } from "@/lib/api";
import type { HitterRow, PitcherRow, PlayerType } from "@/lib/types";

export default function HomePage() {
  const [playerType, setPlayerType] = useState<PlayerType>("hitters");
  const [hitters, setHitters] = useState<HitterRow[]>([]);
  const [pitchers, setPitchers] = useState<PitcherRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Track which types have already been successfully fetched so we
  // don't re-download when the user toggles back.
  const fetched = useRef<Set<PlayerType>>(new Set());

  const load = useCallback(async (type: PlayerType) => {
    if (fetched.current.has(type)) return;
    setLoading(true);
    setError(null);
    try {
      if (type === "hitters") {
        const data = await fetchHitters();
        setHitters(data);
      } else {
        const data = await fetchPitchers();
        setPitchers(data);
      }
      fetched.current.add(type);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "An unknown error occurred."
      );
    } finally {
      setLoading(false);
    }
  }, []); // all dependencies are stable refs or module-level functions

  useEffect(() => {
    load(playerType);
  }, [playerType, load]);

  const retry = () => {
    fetched.current.delete(playerType);
    setError(null);
    load(playerType);
  };

  const currentPlayers = playerType === "hitters" ? hitters : pitchers;

  return (
    <main className="min-h-screen bg-gray-950">
      {/* ── Sticky header ── */}
      <header className="sticky top-0 z-10 border-b border-gray-800 bg-gray-900/95 backdrop-blur-sm">
        <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">
              ⚾ Fantasy Baseball Rankings
            </h1>
            <p className="text-xs text-gray-500 mt-0.5">
              2025 MLB Season · Z-Score Rankings · Data via FanGraphs / pybaseball
            </p>
          </div>
          <Toggle value={playerType} onChange={setPlayerType} />
        </div>
      </header>

      {/* ── Main content ── */}
      <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 py-6">
        {/* Info bar */}
        <div className="flex flex-wrap items-center justify-between gap-2 mb-4 text-xs text-gray-500">
          <span>
            {currentPlayers.length > 0
              ? `Top ${currentPlayers.length} ${playerType} · ranked by total fantasy z-score`
              : `Waiting for ${playerType} data…`}
          </span>
          <span className="hidden sm:inline">
            Filters: AB ≥ 100 (hitters) · IP ≥ 20 (pitchers) · Rate stats weighted by AB / IP
          </span>
        </div>

        {/* ── Loading ── */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-40 gap-5">
            <div className="w-12 h-12 rounded-full border-[3px] border-blue-600 border-t-transparent animate-spin" />
            <div className="text-center space-y-1">
              <p className="text-gray-200 font-medium">Crunching 2025 stats…</p>
              <p className="text-gray-500 text-xs">
                First load pulls data from FanGraphs — may take 15–45 seconds.
                <br />
                Subsequent loads use a local 12-hour cache.
              </p>
            </div>
          </div>
        )}

        {/* ── Error ── */}
        {!loading && error && (
          <div className="max-w-2xl mx-auto mt-8 bg-red-950/40 border border-red-800 rounded-2xl p-6 space-y-3">
            <h2 className="text-red-300 font-semibold">Failed to load data</h2>
            <pre className="text-red-400 text-xs font-mono whitespace-pre-wrap break-all bg-black/30 rounded-lg p-3">
              {error}
            </pre>
            <p className="text-gray-500 text-xs">
              Make sure the backend is running:{" "}
              <code className="text-gray-300 bg-gray-800 px-1.5 py-0.5 rounded">
                uvicorn main:app --reload --port 8000
              </code>
            </p>
            <button
              onClick={retry}
              className="px-4 py-2 bg-red-800 hover:bg-red-700 active:bg-red-900 text-white text-sm rounded-lg transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {/* ── Table ── */}
        {!loading && !error && currentPlayers.length > 0 &&
          (playerType === "hitters" ? (
            <PlayerTable players={hitters} type="hitters" />
          ) : (
            <PlayerTable players={pitchers} type="pitchers" />
          ))}
      </div>
    </main>
  );
}

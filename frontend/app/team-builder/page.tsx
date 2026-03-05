"use client";

import { useState, useEffect, useCallback } from "react";
import PlayerPicker from "@/components/PlayerPicker";
import RosterTable from "@/components/RosterTable";
import TimeframeSelector from "@/components/TimeframeSelector";
import StatControls from "@/components/StatControls";
import { fetchGroupedPlayers } from "@/lib/api";
import { useApp } from "@/context/AppContext";
import { loadTeam, saveTeam, clearTeam, emptyTeam } from "@/lib/store";
import type {
  GroupedPlayersResponse,
  MyTeam,
  PlayerRow,
} from "@/lib/types";

type ActiveSlot = "hitters" | "pitchers" | "il";

const IL_LIMIT = 3;

export default function TeamBuilderPage() {
  const { timeframe, displayMode, includedHitterStats, includedPitcherStats } = useApp();

  const [data, setData] = useState<GroupedPlayersResponse | null>(null);
  const [hldAvailable, setHldAvailable] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [team, setTeam] = useState<MyTeam>(emptyTeam());
  const [activeSlot, setActiveSlot] = useState<ActiveSlot>("hitters");
  const [view, setView] = useState<"picker" | "roster">("picker");

  // Load team from localStorage on mount
  useEffect(() => {
    setTeam(loadTeam());
  }, []);

  // Fetch grouped players when timeframe changes
  const loadData = useCallback(async (tf: typeof timeframe) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchGroupedPlayers(2025, tf);
      setData(res);
      setHldAvailable(res.hld_available);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load players.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(timeframe);
  }, [timeframe, loadData]);

  // Add player to the active roster slot
  const handleSelect = useCallback(
    (player: PlayerRow) => {
      setTeam((prev) => {
        // IL uses fixed 3 slots
        if (activeSlot === "il") {
          const slots = [...prev.il] as (PlayerRow | null)[];
          const emptyIdx = slots.findIndex((s) => s === null);
          if (emptyIdx === -1) {
            alert(`All ${IL_LIMIT} IL slots are filled. Remove a player first.`);
            return prev;
          }
          slots[emptyIdx] = player;
          const updated = { ...prev, il: slots };
          saveTeam(updated);
          return updated;
        }

        // Hitters and pitchers are unlimited — just append
        const slots = [...prev[activeSlot]] as (PlayerRow | null)[];
        // Prevent duplicate
        if (slots.some((p) => p?.Name === player.Name)) return prev;
        slots.push(player);
        const updated = { ...prev, [activeSlot]: slots };
        saveTeam(updated);
        return updated;
      });
    },
    [activeSlot],
  );

  const handleRemove = useCallback(
    (slot: keyof MyTeam, index: number) => {
      setTeam((prev) => {
        const slots = [...prev[slot]] as (PlayerRow | null)[];
        if (slot === "il") {
          // Fixed slots — set to null to preserve positions
          slots[index] = null;
        } else {
          // Dynamic slots — splice to compact the array
          slots.splice(index, 1);
        }
        const updated = { ...prev, [slot]: slots };
        saveTeam(updated);
        return updated;
      });
    },
    [],
  );

  const handleClear = () => {
    if (confirm("Clear your entire roster?")) {
      setTeam(clearTeam());
    }
  };

  // All selected player names (for picker highlighting)
  const selectedNames = [
    ...team.hitters,
    ...team.pitchers,
    ...team.il,
  ]
    .filter(Boolean)
    .map((p) => p!.Name);

  // Count of filled slots
  const filledCount = (arr: (PlayerRow | null)[]) => arr.filter(Boolean).length;
  const ilCount = filledCount(team.il);

  const pickerPool: "hitters" | "pitchers" | "both" =
    activeSlot === "hitters" ? "hitters" : activeSlot === "pitchers" ? "pitchers" : "both";

  return (
    <main className="min-h-screen bg-gray-950">
      {/* Header */}
      <div className="border-b border-gray-800 bg-gray-900/80">
        <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 py-4 space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h1 className="text-xl font-bold text-white">Team Builder</h1>
              <p className="text-xs text-gray-500 mt-0.5">
                Unlimited Hitters · Unlimited Pitchers · 3 IL
              </p>
            </div>
            <div className="flex items-center gap-2">
              {/* View toggle */}
              <div className="flex rounded-lg bg-gray-800 border border-gray-700 overflow-hidden text-xs font-medium">
                <button
                  onClick={() => setView("picker")}
                  className={`px-3 py-1.5 transition-colors ${
                    view === "picker"
                      ? "bg-blue-600 text-white"
                      : "text-gray-400 hover:text-white"
                  }`}
                >
                  Pick Players
                </button>
                <button
                  onClick={() => setView("roster")}
                  className={`px-3 py-1.5 transition-colors ${
                    view === "roster"
                      ? "bg-blue-600 text-white"
                      : "text-gray-400 hover:text-white"
                  }`}
                >
                  My Roster
                </button>
              </div>
              <button
                onClick={handleClear}
                className="px-3 py-1.5 text-xs text-gray-500 hover:text-red-400 border border-gray-700 rounded-lg transition-colors"
              >
                Clear
              </button>
            </div>
          </div>

          {/* Controls */}
          <div className="flex flex-wrap gap-3">
            <TimeframeSelector />
            <div className="w-px h-4 bg-gray-700 hidden sm:block" />
            <StatControls playerType={activeSlot === "pitchers" ? "pitchers" : "hitters"} />
          </div>
        </div>
      </div>

      <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 py-6">
        {/* Slot selector summary */}
        <div className="flex gap-3 mb-6 flex-wrap">
          {(["hitters", "pitchers", "il"] as ActiveSlot[]).map((slot) => {
            const count =
              slot === "il" ? filledCount(team.il) : team[slot].filter(Boolean).length;
            const isILFull = slot === "il" && ilCount >= IL_LIMIT;
            return (
              <button
                key={slot}
                onClick={() => { setActiveSlot(slot); setView("picker"); }}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
                  activeSlot === slot && view === "picker"
                    ? "border-blue-500 bg-blue-600/20 text-blue-300"
                    : isILFull
                    ? "border-emerald-700 bg-emerald-950/30 text-emerald-400"
                    : "border-gray-700 bg-gray-800/50 text-gray-400 hover:text-white hover:border-gray-600"
                }`}
              >
                <span className="capitalize">{slot}</span>
                <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-gray-700 text-gray-300">
                  {slot === "il" ? `${count}/${IL_LIMIT}` : count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 bg-red-950/40 border border-red-800 rounded-xl p-4 text-sm text-red-300">
            {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-20 gap-3">
            <div className="w-8 h-8 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
            <p className="text-gray-400 text-sm">Loading players…</p>
          </div>
        )}

        {/* Picker / Roster view */}
        {!loading && (
          <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-6">
            {/* Left — Player picker */}
            {view === "picker" && (
              <div className="lg:sticky lg:top-16 lg:self-start">
                <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
                  {/* Slot selector */}
                  <div className="flex gap-1 mb-3 flex-wrap">
                    {(["hitters", "pitchers", "il"] as ActiveSlot[]).map((slot) => (
                      <button
                        key={slot}
                        onClick={() => setActiveSlot(slot)}
                        className={`px-2.5 py-1 rounded text-xs font-medium transition-colors capitalize ${
                          activeSlot === slot
                            ? "bg-blue-600 text-white"
                            : "bg-gray-800 text-gray-400 hover:text-white"
                        }`}
                      >
                        {slot}
                      </button>
                    ))}
                  </div>

                  <p className="text-xs text-gray-500 mb-3">
                    Adding to{" "}
                    <span className="text-gray-300 font-medium capitalize">
                      {activeSlot}
                    </span>
                    {activeSlot === "il" && (
                      <> · {ilCount}/{IL_LIMIT} filled</>
                    )}
                  </p>

                  <PlayerPicker
                    data={data}
                    pool={pickerPool}
                    selected={selectedNames}
                    maxSelect={activeSlot === "il" ? IL_LIMIT : undefined}
                    onSelect={handleSelect}
                    selectLabel="Add"
                  />
                </div>
              </div>
            )}

            {/* Right — Roster table */}
            <div className={view === "picker" ? "" : "col-span-full"}>
              <RosterTable
                team={team}
                displayMode={displayMode}
                hldAvailable={hldAvailable}
                includedHitterStats={includedHitterStats}
                includedPitcherStats={includedPitcherStats}
                onRemove={handleRemove}
              />
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

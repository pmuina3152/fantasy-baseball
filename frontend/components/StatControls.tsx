"use client";

import { useApp } from "@/context/AppContext";
import {
  ALL_HITTER_STAT_KEYS,
  ALL_PITCHER_STAT_KEYS,
  HITTER_STAT_LABELS,
  PITCHER_STAT_LABELS,
  type HitterStatKey,
  type PitcherStatKey,
} from "@/lib/types";

interface Props {
  playerType: "hitters" | "pitchers";
}

export default function StatControls({ playerType }: Props) {
  const {
    displayMode,
    setDisplayMode,
    includedHitterStats,
    includedPitcherStats,
    toggleHitterStat,
    togglePitcherStat,
    resetStats,
  } = useApp();

  const isHitters = playerType === "hitters";
  const keys = isHitters ? ALL_HITTER_STAT_KEYS : ALL_PITCHER_STAT_KEYS;
  const included = isHitters ? includedHitterStats : includedPitcherStats;
  const toggle = isHitters ? toggleHitterStat : togglePitcherStat;
  const labels = isHitters ? HITTER_STAT_LABELS : PITCHER_STAT_LABELS;

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Display mode pill */}
      <div className="flex items-center rounded-full bg-gray-800 border border-gray-700 text-xs font-medium overflow-hidden">
        <button
          onClick={() => setDisplayMode("zscore")}
          className={`px-3 py-1.5 transition-colors ${
            displayMode === "zscore"
              ? "bg-blue-600 text-white"
              : "text-gray-400 hover:text-white"
          }`}
        >
          Z-Score
        </button>
        <button
          onClick={() => setDisplayMode("raw")}
          className={`px-3 py-1.5 transition-colors ${
            displayMode === "raw"
              ? "bg-blue-600 text-white"
              : "text-gray-400 hover:text-white"
          }`}
        >
          Raw
        </button>
      </div>

      {/* Stat checkboxes */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-xs text-gray-500">Stats:</span>
        {(keys as string[]).map((key) => {
          const active = (included as Set<string>).has(key);
          const label = (labels as Record<string, string>)[key];

          return (
            <button
              key={key}
              onClick={() => (toggle as (k: string) => void)(key)}
              className={`px-2.5 py-1 rounded text-xs font-medium border transition-colors ${
                active
                  ? "border-blue-500 bg-blue-600/20 text-blue-300"
                  : "border-gray-700 bg-gray-800/60 text-gray-500 hover:text-gray-300"
              }`}
            >
              {label}
            </button>
          );
        })}
        <button
          onClick={resetStats}
          className="px-2 py-1 text-xs text-gray-600 hover:text-gray-400 transition-colors"
        >
          Reset
        </button>
      </div>
    </div>
  );
}

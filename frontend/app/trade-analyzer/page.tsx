"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import PlayerPicker from "@/components/PlayerPicker";
import DeltaChart from "@/components/DeltaChart";
import TimeframeSelector from "@/components/TimeframeSelector";
import StatControls from "@/components/StatControls";
import { fetchGroupedPlayers } from "@/lib/api";
import { useApp } from "@/context/AppContext";
import {
  deltaMixedStats,
  computeTradeResult,
  sumHitterStats,
  sumPitcherStats,
  isHitter,
  type TradeResult,
} from "@/lib/utils";
import type {
  DisplayMode,
  GroupedPlayersResponse,
  HitterRow,
  HitterStatKey,
  PitcherRow,
  PitcherStatKey,
  PlayerRow,
  StatDelta,
} from "@/lib/types";

// Maps z-key → raw stat key (for "Raw" display mode in SideSummary)
const HITTER_ZKEY_TO_RAW: Record<HitterStatKey, string> = {
  zR: "R", zHR: "HR", zRBI: "RBI", zSB: "SB", zAVG: "AVG",
};
const PITCHER_ZKEY_TO_RAW: Record<PitcherStatKey, string> = {
  zK: "K", zW: "W", zSV: "SV", zHLD: "HLD", zERA: "ERA", zWHIP: "WHIP",
};

// Decimal places for raw stat display
const RAW_DECIMALS: Record<string, number> = {
  AVG: 3, ERA: 2, WHIP: 3,
};

function fz(v: number | undefined) {
  if (v === undefined) return "—";
  return (v > 0 ? "+" : "") + v.toFixed(2);
}

function fRaw(key: string, v: number | undefined) {
  if (v === undefined) return "—";
  const d = RAW_DECIMALS[key];
  return d !== undefined ? v.toFixed(d) : v.toFixed(0);
}

function zC(v: number | undefined) {
  if (v === undefined) return "text-gray-400";
  if (v >= 1)  return "text-emerald-400";
  if (v >= 0)  return "text-gray-300";
  if (v >= -1) return "text-orange-400";
  return "text-red-400";
}

// ── Side summary (player list + stat totals) ──────────────────────────────────

function SideSummary({
  label,
  accentClass,
  players,
  displayMode,
  includedHitterStats,
  includedPitcherStats,
  onRemove,
}: {
  label: string;
  accentClass: string;
  players: PlayerRow[];
  displayMode: DisplayMode;
  includedHitterStats: Set<HitterStatKey>;
  includedPitcherStats: Set<PitcherStatKey>;
  onRemove: (name: string) => void;
}) {
  const hitters = players.filter(isHitter) as HitterRow[];
  const pitchers = players.filter((p) => !isHitter(p)) as PitcherRow[];
  const hTotals = sumHitterStats(hitters);
  const pTotals = sumPitcherStats(pitchers);

  const allHitterKeys: HitterStatKey[] = ["zR", "zHR", "zRBI", "zSB", "zAVG"];
  const allPitcherKeys: PitcherStatKey[] = ["zK", "zW", "zSV", "zHLD", "zERA", "zWHIP"];
  const activeHitterKeys = allHitterKeys.filter((k) => includedHitterStats.has(k));
  const activePitcherKeys = allPitcherKeys.filter((k) => includedPitcherStats.has(k));

  const isRaw = displayMode === "raw";

  return (
    <div>
      <h3 className={`text-sm font-semibold mb-2 ${accentClass}`}>{label}</h3>
      {players.length === 0 ? (
        <p className="text-gray-600 text-xs italic text-center py-4">No players selected</p>
      ) : (
        <div className="space-y-1 mb-3">
          {players.map((p) => (
            <div
              key={p.Name}
              className="flex items-center justify-between gap-2 px-3 py-1.5 bg-gray-800/60 rounded-lg text-sm"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className={`text-[10px] px-1 py-0.5 rounded font-medium shrink-0 ${
                  isHitter(p) ? "bg-green-900/60 text-green-300" : "bg-purple-900/60 text-purple-300"
                }`}>
                  {isHitter(p) ? "H" : "P"}
                </span>
                <span className="font-medium text-white truncate">{p.Name}</span>
                <span className="text-gray-500 text-xs shrink-0">{p.Team ?? "—"}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`text-xs font-semibold ${zC(p.total_z)}`}>{fz(p.total_z)}z</span>
                <button
                  onClick={() => onRemove(p.Name)}
                  className="text-gray-600 hover:text-red-400 text-xs transition-colors"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {(hTotals || pTotals) && (
        <div className="bg-gray-800/40 rounded-lg p-3 space-y-2 text-xs">
          {hTotals && activeHitterKeys.length > 0 && (
            <div>
              <p className="text-gray-500 mb-1 font-medium">
                Hitter {isRaw ? "totals" : "z-totals"}
              </p>
              <div
                className="grid gap-1"
                style={{ gridTemplateColumns: `repeat(${activeHitterKeys.length}, minmax(0, 1fr))` }}
              >
                {activeHitterKeys.map((k) => {
                  const rawKey = HITTER_ZKEY_TO_RAW[k];
                  const displayKey = isRaw ? rawKey : k;
                  const val = (hTotals as Record<string, number>)[displayKey];
                  return (
                    <div key={k} className="text-center">
                      <div className="text-gray-600">{rawKey}</div>
                      <div className={`font-semibold ${isRaw ? "text-gray-200" : zC(val)}`}>
                        {isRaw ? fRaw(rawKey, val) : fz(val)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {pTotals && activePitcherKeys.length > 0 && (
            <div>
              <p className="text-gray-500 mb-1 font-medium">
                Pitcher {isRaw ? "totals" : "z-totals"}
              </p>
              <div
                className="grid gap-1"
                style={{ gridTemplateColumns: `repeat(${activePitcherKeys.length}, minmax(0, 1fr))` }}
              >
                {activePitcherKeys.map((k) => {
                  const rawKey = PITCHER_ZKEY_TO_RAW[k];
                  const displayKey = isRaw ? rawKey : k;
                  const val = (pTotals as Record<string, number>)[displayKey];
                  return (
                    <div key={k} className="text-center">
                      <div className="text-gray-600">{rawKey}</div>
                      <div className={`font-semibold ${isRaw ? "text-gray-200" : zC(val)}`}>
                        {isRaw ? fRaw(rawKey, val) : fz(val)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Team result panel ─────────────────────────────────────────────────────────

function TeamResult({
  label,
  accentClass,
  borderClass,
  result,
  chartDeltas,
}: {
  label: string;
  accentClass: string;
  borderClass: string;
  result: TradeResult;
  chartDeltas: StatDelta[];
}) {
  const hasMoves = result.gained.length > 0 || result.lost.length > 0;

  return (
    <div className={`bg-gray-900 border ${borderClass} rounded-xl p-5 space-y-4`}>
      <div className="flex items-center justify-between">
        <h3 className={`font-bold text-base ${accentClass}`}>{label}</h3>
        <span className={`text-sm font-bold px-2 py-1 rounded ${
          result.totalZ >= 0 ? "bg-emerald-900/50 text-emerald-300" : "bg-red-900/50 text-red-300"
        }`}>
          {result.totalZ > 0 ? "+" : ""}{result.totalZ.toFixed(2)} z net
        </span>
      </div>

      {!hasMoves ? (
        <p className="text-gray-600 text-xs italic">Select players on both sides to see results.</p>
      ) : (
        <>
          {result.gained.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-emerald-400 mb-1.5">
                Gains ({result.gained.length} {result.gained.length === 1 ? "category" : "categories"})
              </p>
              <div className="space-y-1">
                {result.gained.map((d) => (
                  <div key={d.stat} className="flex items-center justify-between text-xs px-2 py-1 bg-emerald-950/30 rounded">
                    <span className="text-gray-300 font-medium">{d.label}</span>
                    <span className="text-emerald-400 font-semibold tabular-nums">+{d.delta.toFixed(2)} z</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {result.lost.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-red-400 mb-1.5">
                Losses ({result.lost.length} {result.lost.length === 1 ? "category" : "categories"})
              </p>
              <div className="space-y-1">
                {result.lost.map((d) => (
                  <div key={d.stat} className="flex items-center justify-between text-xs px-2 py-1 bg-red-950/30 rounded">
                    <span className="text-gray-300 font-medium">{d.label}</span>
                    <span className="text-red-400 font-semibold tabular-nums">{d.delta.toFixed(2)} z</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <DeltaChart deltas={chartDeltas} title="Delta by category (z-score)" />
        </>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TradeAnalyzerPage() {
  const {
    timeframe,
    displayMode,
    includedHitterStats,
    includedPitcherStats,
  } = useApp();

  const [data, setData] = useState<GroupedPlayersResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [sideA, setSideA] = useState<PlayerRow[]>([]);
  const [sideB, setSideB] = useState<PlayerRow[]>([]);
  const [activeSide, setActiveSide] = useState<"A" | "B">("A");

  const loadData = useCallback(async (tf: typeof timeframe) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchGroupedPlayers(2025, tf);
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load players.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(timeframe);
    setSideA([]);
    setSideB([]);
  }, [timeframe, loadData]);

  const handleSelect = useCallback(
    (player: PlayerRow) => {
      if (activeSide === "A") {
        setSideA((prev) => {
          if (prev.find((p) => p.Name === player.Name)) return prev;
          return [...prev, player];
        });
      } else {
        setSideB((prev) => {
          if (prev.find((p) => p.Name === player.Name)) return prev;
          return [...prev, player];
        });
      }
    },
    [activeSide],
  );

  const removeFromA = (name: string) =>
    setSideA((prev) => prev.filter((p) => p.Name !== name));
  const removeFromB = (name: string) =>
    setSideB((prev) => prev.filter((p) => p.Name !== name));

  // Full deltas across all stats
  const allDeltas: StatDelta[] = useMemo(() => deltaMixedStats(sideA, sideB), [sideA, sideB]);

  // Filter to enabled stats
  const deltas = useMemo(
    () =>
      allDeltas.filter(
        (d) =>
          includedHitterStats.has(d.stat as HitterStatKey) ||
          includedPitcherStats.has(d.stat as PitcherStatKey),
      ),
    [allDeltas, includedHitterStats, includedPitcherStats],
  );

  const resultA = useMemo(() => computeTradeResult(deltas, "A"), [deltas]);
  const resultB = useMemo(() => computeTradeResult(deltas, "B"), [deltas]);

  const chartDeltasB = useMemo(
    () => deltas.map((d) => ({ ...d, delta: -d.delta, sideA: d.sideB, sideB: d.sideA })),
    [deltas],
  );

  const allSelected = [...sideA.map((p) => p.Name), ...sideB.map((p) => p.Name)];

  return (
    <main className="min-h-screen bg-gray-950">
      {/* ── Header with controls ── */}
      <div className="border-b border-gray-800 bg-gray-900/80">
        <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 py-4 space-y-3">
          <div>
            <h1 className="text-xl font-bold text-white">Trade Analyzer</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              Add any number of players per side · results update with stat toggles
            </p>
          </div>

          {/* Controls — same pattern as /rankings */}
          <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
            <TimeframeSelector />
            <div className="w-px h-4 bg-gray-700 hidden sm:block self-center" />
            <div className="flex flex-col gap-2">
              <StatControls playerType="hitters" />
              <StatControls playerType="pitchers" />
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 py-6">
        {error && (
          <div className="mb-4 bg-red-950/40 border border-red-800 rounded-xl p-4 text-sm text-red-300">
            {error}
          </div>
        )}

        {loading && (
          <div className="flex items-center justify-center py-20 gap-3">
            <div className="w-8 h-8 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
            <p className="text-gray-400 text-sm">Loading players…</p>
          </div>
        )}

        {!loading && (
          <div className="grid grid-cols-1 xl:grid-cols-[300px_1fr] gap-6">
            {/* ── Left: Player picker ── */}
            <div className="xl:sticky xl:top-16 xl:self-start">
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
                {/* Side selector */}
                <div className="flex gap-1 mb-4">
                  <button
                    onClick={() => setActiveSide("A")}
                    className={`flex-1 py-1.5 rounded-lg text-sm font-semibold transition-colors ${
                      activeSide === "A"
                        ? "bg-blue-600 text-white"
                        : "bg-gray-800 text-gray-400 hover:text-white"
                    }`}
                  >
                    Side A ({sideA.length})
                  </button>
                  <button
                    onClick={() => setActiveSide("B")}
                    className={`flex-1 py-1.5 rounded-lg text-sm font-semibold transition-colors ${
                      activeSide === "B"
                        ? "bg-orange-600 text-white"
                        : "bg-gray-800 text-gray-400 hover:text-white"
                    }`}
                  >
                    Side B ({sideB.length})
                  </button>
                </div>

                <p className="text-xs text-gray-500 mb-3">
                  Picking for{" "}
                  <span className={`font-semibold ${activeSide === "A" ? "text-blue-400" : "text-orange-400"}`}>
                    Side {activeSide}
                  </span>
                </p>

                <PlayerPicker
                  data={data}
                  pool="both"
                  selected={allSelected}
                  onSelect={handleSelect}
                  selectLabel={`→ ${activeSide}`}
                />
              </div>
            </div>

            {/* ── Right: Results ── */}
            <div className="space-y-6">
              {/* Side summaries */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="bg-gray-900 border border-blue-900/40 rounded-xl p-4">
                  <SideSummary
                    label="Side A — giving up"
                    accentClass="text-blue-300"
                    players={sideA}
                    displayMode={displayMode}
                    includedHitterStats={includedHitterStats}
                    includedPitcherStats={includedPitcherStats}
                    onRemove={removeFromA}
                  />
                </div>
                <div className="bg-gray-900 border border-orange-900/40 rounded-xl p-4">
                  <SideSummary
                    label="Side B — receiving"
                    accentClass="text-orange-300"
                    players={sideB}
                    displayMode={displayMode}
                    includedHitterStats={includedHitterStats}
                    includedPitcherStats={includedPitcherStats}
                    onRemove={removeFromB}
                  />
                </div>
              </div>

              {/* Team results (always z-score for meaningful delta analysis) */}
              {deltas.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <TeamResult
                    label="Team A Result"
                    accentClass="text-blue-300"
                    borderClass="border-blue-900/40"
                    result={resultA}
                    chartDeltas={deltas}
                  />
                  <TeamResult
                    label="Team B Result"
                    accentClass="text-orange-300"
                    borderClass="border-orange-900/40"
                    result={resultB}
                    chartDeltas={chartDeltasB}
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

"use client";

import { useMemo } from "react";
import type {
  DisplayMode,
  HitterRow,
  HitterStatKey,
  PitcherRow,
  PitcherStatKey,
} from "@/lib/types";
import {
  recomputeHitterZ,
  recomputePitcherZ,
  renormalise,
} from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

type Props =
  | {
      players: HitterRow[];
      type: "hitters";
      displayMode?: DisplayMode;
      includedStats?: Set<HitterStatKey>;
    }
  | {
      players: PitcherRow[];
      type: "pitchers";
      displayMode?: DisplayMode;
      includedStats?: Set<PitcherStatKey>;
      hldAvailable?: boolean;
    };

// ── Column definitions ────────────────────────────────────────────────────────

interface ColDef {
  key: string;
  label: string;
  isZ?: boolean;
  isScore?: boolean;
  isRank?: boolean;
  decimals?: number;
  align?: "left" | "center" | "right";
  /** z-key this column corresponds to; used for include/exclude filtering */
  statZKey?: HitterStatKey | PitcherStatKey;
}

// Maps any column key (raw or z) to its corresponding z-stat key
const HITTER_COL_ZKEY: Record<string, HitterStatKey> = {
  R: "zR",   zR: "zR",
  HR: "zHR", zHR: "zHR",
  RBI: "zRBI", zRBI: "zRBI",
  SB: "zSB", zSB: "zSB",
  AVG: "zAVG", zAVG: "zAVG",
};

const PITCHER_COL_ZKEY: Record<string, PitcherStatKey> = {
  K: "zK",   zK: "zK",
  W: "zW",   zW: "zW",
  SV: "zSV", zSV: "zSV",
  HLD: "zHLD", zHLD: "zHLD",
  ERA: "zERA", zERA: "zERA",
  WHIP: "zWHIP", zWHIP: "zWHIP",
};

const BASE_COLS: ColDef[] = [
  { key: "base_rank",   label: "Base",    isRank: true,  align: "center" },
  { key: "rank",        label: "Rank",    isRank: true,  align: "center" },
  { key: "Name",        label: "Name",    align: "left"   },
  { key: "Team",        label: "Team",    align: "center" },
  { key: "score_0_100", label: "Score",   isScore: true,  align: "center" },
  { key: "total_z",     label: "Total Z", isZ: true, decimals: 2, align: "center" },
];

function buildHitterCols(
  mode: DisplayMode,
  included: Set<HitterStatKey> | undefined,
): ColDef[] {
  const statCols: ColDef[] =
    mode === "zscore"
      ? [
          { key: "zR",   label: "zR",   isZ: true, decimals: 2, align: "center", statZKey: "zR"   },
          { key: "zHR",  label: "zHR",  isZ: true, decimals: 2, align: "center", statZKey: "zHR"  },
          { key: "zRBI", label: "zRBI", isZ: true, decimals: 2, align: "center", statZKey: "zRBI" },
          { key: "zSB",  label: "zSB",  isZ: true, decimals: 2, align: "center", statZKey: "zSB"  },
          { key: "zAVG", label: "zAVG", isZ: true, decimals: 2, align: "center", statZKey: "zAVG" },
        ]
      : [
          { key: "R",   label: "R",   align: "center", statZKey: "zR"   },
          { key: "HR",  label: "HR",  align: "center", statZKey: "zHR"  },
          { key: "RBI", label: "RBI", align: "center", statZKey: "zRBI" },
          { key: "SB",  label: "SB",  align: "center", statZKey: "zSB"  },
          { key: "AVG", label: "AVG", decimals: 3, align: "center", statZKey: "zAVG" },
        ];

  const filtered = included
    ? statCols.filter((c) => included.has(HITTER_COL_ZKEY[c.key] ?? (c.statZKey as HitterStatKey)))
    : statCols;

  return [...BASE_COLS, ...filtered];
}

function buildPitcherCols(
  mode: DisplayMode,
  hldAvailable: boolean,
  included: Set<PitcherStatKey> | undefined,
): ColDef[] {
  const statCols: ColDef[] =
    mode === "zscore"
      ? [
          { key: "zK",    label: "zK",    isZ: true, decimals: 2, align: "center", statZKey: "zK"    },
          { key: "zW",    label: "zW",    isZ: true, decimals: 2, align: "center", statZKey: "zW"    },
          { key: "zSV",   label: "zSV",   isZ: true, decimals: 2, align: "center", statZKey: "zSV"   },
          ...(hldAvailable
            ? [{ key: "zHLD", label: "zHLD", isZ: true, decimals: 2, align: "center" as const, statZKey: "zHLD" as PitcherStatKey }]
            : []),
          { key: "zERA",  label: "zERA",  isZ: true, decimals: 2, align: "center", statZKey: "zERA"  },
          { key: "zWHIP", label: "zWHIP", isZ: true, decimals: 2, align: "center", statZKey: "zWHIP" },
        ]
      : [
          { key: "K",    label: "K",    align: "center", statZKey: "zK"    },
          { key: "W",    label: "W",    align: "center", statZKey: "zW"    },
          { key: "SV",   label: "SV",   align: "center", statZKey: "zSV"   },
          ...(hldAvailable
            ? [{ key: "HLD", label: "HLD", align: "center" as const, statZKey: "zHLD" as PitcherStatKey }]
            : []),
          { key: "ERA",  label: "ERA",  decimals: 2, align: "center", statZKey: "zERA"  },
          { key: "WHIP", label: "WHIP", decimals: 3, align: "center", statZKey: "zWHIP" },
        ];

  const filtered = included
    ? statCols.filter((c) =>
        included.has(PITCHER_COL_ZKEY[c.key] ?? (c.statZKey as PitcherStatKey)),
      )
    : statCols;

  return [...BASE_COLS, ...filtered];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function zColour(val: unknown): string {
  if (typeof val !== "number") return "text-gray-400";
  if (val >= 1.5)  return "text-emerald-300 font-semibold";
  if (val >= 0.5)  return "text-emerald-500";
  if (val >= -0.5) return "text-gray-300";
  if (val >= -1.5) return "text-orange-400";
  return "text-red-400";
}

function fmtZ(val: number, decimals: number): string {
  const s = val.toFixed(decimals);
  return val > 0 ? `+${s}` : s;
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score));
  return (
    <div className="flex items-center justify-center gap-2">
      <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-400"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="tabular-nums text-gray-200 text-xs w-8 text-right">
        {score.toFixed(1)}
      </span>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function PlayerTable(props: Props) {
  const mode = props.displayMode ?? "zscore";
  const hldAvail = props.type === "pitchers" ? (props.hldAvailable ?? true) : false;
  const cols =
    props.type === "hitters"
      ? buildHitterCols(mode, props.includedStats)
      : buildPitcherCols(mode, hldAvail, props.includedStats as Set<PitcherStatKey> | undefined);

  // Recompute total_z from included stats, re-sort, and attach base_rank + rank
  const players = useMemo(() => {
    if (props.type === "hitters") {
      const included = props.includedStats;
      // Preserve base_rank from the original API rank (computed with all stats)
      const withBase = props.players.map((p) => ({ ...p, base_rank: p.rank }));
      if (!included) return withBase;

      const withZ = withBase.map((p) => ({
        ...p,
        total_z: recomputeHitterZ(p, included),
      }));
      const normalised = renormalise(withZ);
      return [...normalised]
        .sort((a, b) => b.total_z - a.total_z)
        .map((p, i) => ({ ...p, rank: i + 1 }));
    }

    // Pitchers
    const included = props.includedStats as Set<PitcherStatKey> | undefined;
    const withBase = props.players.map((p) => ({ ...p, base_rank: p.rank }));
    if (!included) return withBase;

    const withZ = withBase.map((p) => ({
      ...p,
      total_z: recomputePitcherZ(p, included),
    }));
    const normalised = renormalise(withZ);
    return [...normalised]
      .sort((a, b) => b.total_z - a.total_z)
      .map((p, i) => ({ ...p, rank: i + 1 }));
  }, [props.players, props.type, props.includedStats]);

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-800 shadow-2xl">
      <table className="min-w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-800 sticky top-0">
            {cols.map((col) => (
              <th
                key={col.key + col.label}
                scope="col"
                className={`px-3 py-3 text-xs font-semibold uppercase tracking-wide whitespace-nowrap select-none ${
                  col.isZ ? "text-blue-400" : col.isRank ? "text-gray-500" : "text-gray-400"
                } ${col.align === "left" ? "text-left" : "text-center"}`}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {(players as Record<string, unknown>[]).map((player, idx) => (
            <tr
              key={`${player["Name"]}-${idx}`}
              className={`border-t border-gray-800/60 hover:bg-gray-800/50 transition-colors ${
                idx % 2 === 0 ? "bg-gray-900" : "bg-gray-900/50"
              }`}
            >
              {cols.map((col) => {
                const val = player[col.key];

                if (col.isRank) {
                  return (
                    <td
                      key={col.key + col.label}
                      className={`px-3 py-2.5 text-center font-mono text-xs w-10 ${
                        col.key === "base_rank" ? "text-gray-600" : "text-gray-400"
                      }`}
                    >
                      {val != null ? String(val) : "—"}
                    </td>
                  );
                }
                if (col.key === "Name") {
                  return (
                    <td key={col.key + col.label} className="px-3 py-2.5 text-left font-medium text-white whitespace-nowrap">
                      {String(val ?? "—")}
                    </td>
                  );
                }
                if (col.key === "Team") {
                  return (
                    <td key={col.key + col.label} className="px-3 py-2.5 text-center text-gray-400 text-xs whitespace-nowrap">
                      {val != null ? String(val) : "—"}
                    </td>
                  );
                }
                if (col.isScore && typeof val === "number") {
                  return (
                    <td key={col.key + col.label} className="px-3 py-2.5 text-center">
                      <ScoreBar score={val} />
                    </td>
                  );
                }
                if (col.isZ) {
                  return (
                    <td
                      key={col.key + col.label}
                      className={`px-3 py-2.5 text-center tabular-nums ${zColour(val)}`}
                    >
                      {typeof val === "number"
                        ? fmtZ(val, col.decimals ?? 2)
                        : "—"}
                    </td>
                  );
                }
                return (
                  <td
                    key={col.key + col.label}
                    className={`px-3 py-2.5 tabular-nums text-gray-200 ${
                      col.align === "left" ? "text-left" : "text-center"
                    }`}
                  >
                    {typeof val === "number"
                      ? col.decimals !== undefined
                        ? val.toFixed(col.decimals)
                        : String(val)
                      : String(val ?? "—")}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

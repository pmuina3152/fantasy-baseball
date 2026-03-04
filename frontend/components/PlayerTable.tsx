"use client";

import type { HitterRow, PitcherRow } from "@/lib/types";

type Props =
  | { players: HitterRow[]; type: "hitters" }
  | { players: PitcherRow[]; type: "pitchers" };

interface ColDef {
  key: string;
  label: string;
  /** Is this a z-score column? (coloured + signed) */
  isZ?: boolean;
  /** Is this the 0-100 score? (renders a bar) */
  isScore?: boolean;
  /** Decimal places for numeric display */
  decimals?: number;
  align?: "left" | "center" | "right";
}

// ── Column definitions ────────────────────────────────────────────────────────

const HITTER_COLS: ColDef[] = [
  { key: "rank",        label: "#",       align: "center" },
  { key: "Name",        label: "Name",    align: "left"   },
  { key: "Team",        label: "Team",    align: "center" },
  { key: "score_0_100", label: "Score",   isScore: true,  align: "center" },
  { key: "total_z",     label: "Total Z", isZ: true, decimals: 2, align: "center" },
  { key: "R",   label: "R",    align: "center" },
  { key: "zR",  label: "zR",   isZ: true, decimals: 2, align: "center" },
  { key: "HR",  label: "HR",   align: "center" },
  { key: "zHR", label: "zHR",  isZ: true, decimals: 2, align: "center" },
  { key: "RBI",  label: "RBI",  align: "center" },
  { key: "zRBI", label: "zRBI", isZ: true, decimals: 2, align: "center" },
  { key: "SB",  label: "SB",   align: "center" },
  { key: "zSB", label: "zSB",  isZ: true, decimals: 2, align: "center" },
  { key: "AVG",  label: "AVG",  decimals: 3, align: "center" },
  { key: "zAVG", label: "zAVG", isZ: true, decimals: 2, align: "center" },
];

const PITCHER_COLS: ColDef[] = [
  { key: "rank",        label: "#",       align: "center" },
  { key: "Name",        label: "Name",    align: "left"   },
  { key: "Team",        label: "Team",    align: "center" },
  { key: "score_0_100", label: "Score",   isScore: true,  align: "center" },
  { key: "total_z",     label: "Total Z", isZ: true, decimals: 2, align: "center" },
  { key: "K",   label: "K",    align: "center" },
  { key: "zK",  label: "zK",   isZ: true, decimals: 2, align: "center" },
  { key: "W",   label: "W",    align: "center" },
  { key: "zW",  label: "zW",   isZ: true, decimals: 2, align: "center" },
  { key: "SV",   label: "SV",   align: "center" },
  { key: "zSV",  label: "zSV",  isZ: true, decimals: 2, align: "center" },
  { key: "HLD",  label: "HLD",  align: "center" },
  { key: "zHLD", label: "zHLD", isZ: true, decimals: 2, align: "center" },
  { key: "ERA",  label: "ERA",  decimals: 2, align: "center" },
  { key: "zERA", label: "zERA", isZ: true, decimals: 2, align: "center" },
  { key: "WHIP",  label: "WHIP",  decimals: 3, align: "center" },
  { key: "zWHIP", label: "zWHIP", isZ: true, decimals: 2, align: "center" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Tailwind text-colour class based on z-score magnitude. */
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

/** Mini progress bar for the 0–100 score column. */
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

export default function PlayerTable({ players, type }: Props) {
  const cols = type === "hitters" ? HITTER_COLS : PITCHER_COLS;

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-800 shadow-2xl">
      <table className="min-w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-800 sticky top-0">
            {cols.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={`px-3 py-3 text-xs font-semibold uppercase tracking-wide whitespace-nowrap select-none ${
                  col.isZ ? "text-blue-400" : "text-gray-400"
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

                // Rank
                if (col.key === "rank") {
                  return (
                    <td key={col.key} className="px-3 py-2.5 text-center text-gray-500 font-mono text-xs w-10">
                      {String(val)}
                    </td>
                  );
                }

                // Name
                if (col.key === "Name") {
                  return (
                    <td key={col.key} className="px-3 py-2.5 text-left font-medium text-white whitespace-nowrap">
                      {String(val ?? "—")}
                    </td>
                  );
                }

                // Team
                if (col.key === "Team") {
                  return (
                    <td key={col.key} className="px-3 py-2.5 text-center text-gray-400 text-xs whitespace-nowrap">
                      {val != null ? String(val) : "—"}
                    </td>
                  );
                }

                // Score bar
                if (col.isScore && typeof val === "number") {
                  return (
                    <td key={col.key} className="px-3 py-2.5 text-center">
                      <ScoreBar score={val} />
                    </td>
                  );
                }

                // Z-score columns
                if (col.isZ) {
                  return (
                    <td
                      key={col.key}
                      className={`px-3 py-2.5 text-center tabular-nums ${zColour(val)}`}
                    >
                      {typeof val === "number"
                        ? fmtZ(val, col.decimals ?? 2)
                        : "—"}
                    </td>
                  );
                }

                // Generic numeric / string
                return (
                  <td
                    key={col.key}
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

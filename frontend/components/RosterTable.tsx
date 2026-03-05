"use client";

import type {
  DisplayMode,
  HitterRow,
  HitterStatKey,
  MyTeam,
  PitcherRow,
  PitcherStatKey,
  PlayerRow,
} from "@/lib/types";
import { sumHitterStats, sumPitcherStats } from "@/lib/utils";

interface Props {
  team: MyTeam;
  displayMode: DisplayMode;
  hldAvailable: boolean;
  includedHitterStats: Set<HitterStatKey>;
  includedPitcherStats: Set<PitcherStatKey>;
  onRemove: (slot: keyof MyTeam, index: number) => void;
}

function zC(v: number | undefined) {
  if (v === undefined) return "text-gray-400";
  if (v >= 1.5)  return "text-emerald-300";
  if (v >= 0.5)  return "text-emerald-500";
  if (v >= -0.5) return "text-gray-300";
  if (v >= -1.5) return "text-orange-400";
  return "text-red-400";
}

function fz(v: number) {
  return (v > 0 ? "+" : "") + v.toFixed(2);
}

// Maps raw column key → its z-stat key, used for filtering
const HITTER_RAW_TO_ZKEY: Record<string, HitterStatKey> = {
  R: "zR", HR: "zHR", RBI: "zRBI", SB: "zSB", AVG: "zAVG",
};
const PITCHER_RAW_TO_ZKEY: Record<string, PitcherStatKey> = {
  K: "zK", W: "zW", SV: "zSV", HLD: "zHLD", ERA: "zERA", WHIP: "zWHIP",
};

// ── Hitters section ───────────────────────────────────────────────────────────

function HittersSection({
  players,
  displayMode,
  includedStats,
  onRemove,
}: {
  players: (HitterRow | null)[];
  displayMode: DisplayMode;
  includedStats: Set<HitterStatKey>;
  onRemove: (slot: keyof MyTeam, index: number) => void;
}) {
  const allStatCols =
    displayMode === "zscore"
      ? ["zR", "zHR", "zRBI", "zSB", "zAVG"]
      : ["R", "HR", "RBI", "SB", "AVG"];

  // Filter to only included stats
  const statCols = allStatCols.filter((c) => {
    const zKey = (c.startsWith("z") ? c : HITTER_RAW_TO_ZKEY[c]) as HitterStatKey;
    return includedStats.has(zKey);
  });

  const filled = players.filter(Boolean) as HitterRow[];
  const totals = sumHitterStats(filled);

  return (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-gray-300 mb-2">
        Hitters ({filled.length})
      </h3>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="bg-gray-800">
              <th className="px-3 py-2 text-left text-gray-400 w-6">#</th>
              <th className="px-3 py-2 text-left text-gray-400">Player</th>
              <th className="px-3 py-2 text-center text-gray-400">Team</th>
              {statCols.map((c) => (
                <th key={c} className="px-3 py-2 text-center text-blue-400 whitespace-nowrap">
                  {c}
                </th>
              ))}
              <th className="px-3 py-2 text-center text-gray-400">Total Z</th>
              <th className="px-3 py-2 text-center text-gray-400">Rem</th>
            </tr>
          </thead>
          <tbody>
            {filled.length === 0 ? (
              <tr>
                <td colSpan={statCols.length + 4} className="px-3 py-4 text-center text-gray-700 italic">
                  No hitters added yet
                </td>
              </tr>
            ) : (
              filled.map((player, i) => (
                <tr
                  key={player.Name}
                  className={`border-t border-gray-800/60 hover:bg-gray-800/30 ${
                    i % 2 === 0 ? "bg-gray-900" : "bg-gray-900/50"
                  }`}
                >
                  <td className="px-3 py-2 text-center text-gray-600">{i + 1}</td>
                  <td className="px-3 py-2 font-medium text-white whitespace-nowrap">
                    {player.Name}
                  </td>
                  <td className="px-3 py-2 text-center text-gray-400">{player.Team ?? "—"}</td>
                  {statCols.map((c) => {
                    const v = (player as any)[c] as number | undefined;
                    const isZCol = c.startsWith("z");
                    return (
                      <td key={c} className={`px-3 py-2 text-center tabular-nums ${isZCol ? zC(v as number) : "text-gray-200"}`}>
                        {typeof v === "number"
                          ? isZCol ? fz(v) : c === "AVG" ? v.toFixed(3) : v.toFixed(0)
                          : "—"}
                      </td>
                    );
                  })}
                  <td className={`px-3 py-2 text-center tabular-nums font-semibold ${zC(player.total_z)}`}>
                    {fz(player.total_z)}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <button
                      onClick={() => onRemove("hitters", i)}
                      className="text-gray-600 hover:text-red-400 transition-colors"
                      title="Remove player"
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
          {totals && (
            <tfoot>
              <tr className="border-t-2 border-gray-700 bg-gray-800/80">
                <td className="px-3 py-2" colSpan={3} />
                {statCols.map((c) => {
                  const v = (totals as Record<string, number>)[c];
                  const isZCol = c.startsWith("z");
                  return (
                    <td key={c} className={`px-3 py-2 text-center tabular-nums font-semibold ${isZCol ? zC(v) : "text-gray-100"}`}>
                      {typeof v === "number"
                        ? isZCol ? fz(v) : c === "AVG" ? v.toFixed(3) : v.toFixed(0)
                        : "—"}
                    </td>
                  );
                })}
                <td className={`px-3 py-2 text-center tabular-nums font-bold ${zC(totals.total_z)}`}>
                  {fz(totals.total_z)}
                </td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

// ── Pitchers section ──────────────────────────────────────────────────────────

function PitchersSection({
  players,
  displayMode,
  hldAvailable,
  includedStats,
  onRemove,
}: {
  players: (PitcherRow | null)[];
  displayMode: DisplayMode;
  hldAvailable: boolean;
  includedStats: Set<PitcherStatKey>;
  onRemove: (slot: keyof MyTeam, index: number) => void;
}) {
  const allStatCols =
    displayMode === "zscore"
      ? hldAvailable
        ? ["zK", "zW", "zSV", "zHLD", "zERA", "zWHIP"]
        : ["zK", "zW", "zSV", "zERA", "zWHIP"]
      : hldAvailable
      ? ["K", "W", "SV", "HLD", "ERA", "WHIP"]
      : ["K", "W", "SV", "ERA", "WHIP"];

  // Filter to only included stats
  const statCols = allStatCols.filter((c) => {
    const zKey = (c.startsWith("z") ? c : PITCHER_RAW_TO_ZKEY[c]) as PitcherStatKey;
    return includedStats.has(zKey);
  });

  const filled = players.filter(Boolean) as PitcherRow[];
  const totals = sumPitcherStats(filled);

  return (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-gray-300 mb-2">
        Pitchers ({filled.length})
      </h3>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="bg-gray-800">
              <th className="px-3 py-2 text-left text-gray-400 w-6">#</th>
              <th className="px-3 py-2 text-left text-gray-400">Player</th>
              <th className="px-3 py-2 text-center text-gray-400">Team</th>
              {statCols.map((c) => (
                <th key={c} className="px-3 py-2 text-center text-blue-400 whitespace-nowrap">
                  {c}
                </th>
              ))}
              <th className="px-3 py-2 text-center text-gray-400">Total Z</th>
              <th className="px-3 py-2 text-center text-gray-400">Rem</th>
            </tr>
          </thead>
          <tbody>
            {filled.length === 0 ? (
              <tr>
                <td colSpan={statCols.length + 4} className="px-3 py-4 text-center text-gray-700 italic">
                  No pitchers added yet
                </td>
              </tr>
            ) : (
              filled.map((player, i) => (
                <tr
                  key={player.Name}
                  className={`border-t border-gray-800/60 hover:bg-gray-800/30 ${
                    i % 2 === 0 ? "bg-gray-900" : "bg-gray-900/50"
                  }`}
                >
                  <td className="px-3 py-2 text-center text-gray-600">{i + 1}</td>
                  <td className="px-3 py-2 font-medium text-white whitespace-nowrap">
                    {player.Name}
                  </td>
                  <td className="px-3 py-2 text-center text-gray-400">{player.Team ?? "—"}</td>
                  {statCols.map((c) => {
                    const v = (player as any)[c] as number | undefined;
                    const isZCol = c.startsWith("z");
                    return (
                      <td key={c} className={`px-3 py-2 text-center tabular-nums ${isZCol ? zC(v as number) : "text-gray-200"}`}>
                        {typeof v === "number"
                          ? isZCol ? fz(v) : c === "ERA" || c === "WHIP" ? v.toFixed(3) : v.toFixed(0)
                          : "—"}
                      </td>
                    );
                  })}
                  <td className={`px-3 py-2 text-center tabular-nums font-semibold ${zC(player.total_z)}`}>
                    {fz(player.total_z)}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <button
                      onClick={() => onRemove("pitchers", i)}
                      className="text-gray-600 hover:text-red-400 transition-colors"
                      title="Remove player"
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
          {totals && (
            <tfoot>
              <tr className="border-t-2 border-gray-700 bg-gray-800/80">
                <td className="px-3 py-2" colSpan={3} />
                {statCols.map((c) => {
                  const v = (totals as Record<string, number>)[c];
                  const isZCol = c.startsWith("z");
                  return (
                    <td key={c} className={`px-3 py-2 text-center tabular-nums font-semibold ${isZCol ? zC(v) : "text-gray-100"}`}>
                      {typeof v === "number"
                        ? isZCol ? fz(v) : c === "ERA" || c === "WHIP" ? v.toFixed(3) : v.toFixed(0)
                        : "—"}
                    </td>
                  );
                })}
                <td className={`px-3 py-2 text-center tabular-nums font-bold ${zC(totals.total_z)}`}>
                  {fz(totals.total_z)}
                </td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

// ── IL section (fixed 3 slots) ────────────────────────────────────────────────

function ILSection({
  players,
  onRemove,
}: {
  players: (PlayerRow | null)[];
  onRemove: (slot: keyof MyTeam, index: number) => void;
}) {
  const slots = Array.from({ length: 3 }, (_, i) => players[i] ?? null);

  return (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-gray-300 mb-2">IL (3)</h3>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="bg-gray-800">
              <th className="px-3 py-2 text-left text-gray-400 w-6">#</th>
              <th className="px-3 py-2 text-left text-gray-400">Player</th>
              <th className="px-3 py-2 text-center text-gray-400">Team</th>
              <th className="px-3 py-2 text-center text-gray-400">Type</th>
              <th className="px-3 py-2 text-center text-gray-400">Total Z</th>
              <th className="px-3 py-2 text-center text-gray-400">Rem</th>
            </tr>
          </thead>
          <tbody>
            {slots.map((player, i) =>
              player ? (
                <tr
                  key={player.Name}
                  className={`border-t border-gray-800/60 hover:bg-gray-800/30 ${
                    i % 2 === 0 ? "bg-gray-900" : "bg-gray-900/50"
                  }`}
                >
                  <td className="px-3 py-2 text-center text-gray-600">{i + 1}</td>
                  <td className="px-3 py-2 font-medium text-white whitespace-nowrap">
                    {player.Name}
                  </td>
                  <td className="px-3 py-2 text-center text-gray-400">{player.Team ?? "—"}</td>
                  <td className="px-3 py-2 text-center">
                    <span className={`text-[10px] px-1 py-0.5 rounded font-medium ${
                      "ERA" in player ? "bg-purple-900/60 text-purple-300" : "bg-green-900/60 text-green-300"
                    }`}>
                      {"ERA" in player ? "P" : "H"}
                    </span>
                  </td>
                  <td className={`px-3 py-2 text-center tabular-nums font-semibold ${zC(player.total_z)}`}>
                    {fz(player.total_z)}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <button
                      onClick={() => onRemove("il", i)}
                      className="text-gray-600 hover:text-red-400 transition-colors"
                      title="Remove player"
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={i} className="border-t border-gray-800/60">
                  <td className="px-3 py-2 text-center text-gray-700">{i + 1}</td>
                  <td className="px-3 py-2 text-gray-700 italic" colSpan={5}>Empty slot</td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function RosterTable({
  team,
  displayMode,
  hldAvailable,
  includedHitterStats,
  includedPitcherStats,
  onRemove,
}: Props) {
  return (
    <div>
      <HittersSection
        players={team.hitters}
        displayMode={displayMode}
        includedStats={includedHitterStats}
        onRemove={onRemove}
      />
      <PitchersSection
        players={team.pitchers}
        displayMode={displayMode}
        hldAvailable={hldAvailable}
        includedStats={includedPitcherStats}
        onRemove={onRemove}
      />
      <ILSection players={team.il} onRemove={onRemove} />
    </div>
  );
}

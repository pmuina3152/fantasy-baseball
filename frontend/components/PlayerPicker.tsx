"use client";

import { useState, useMemo } from "react";
import type { GroupedPlayersResponse, HitterRow, PitcherRow, PlayerRow } from "@/lib/types";

interface Props {
  data: GroupedPlayersResponse | null;
  /** "hitters" | "pitchers" | "both" — which pool to show */
  pool: "hitters" | "pitchers" | "both";
  /** Already-selected player names (shown as dimmed / selected) */
  selected?: string[];
  /** Max number of selections (for trade analyzer) */
  maxSelect?: number;
  /** Single-select mode: fires on every click */
  onSelect: (player: PlayerRow) => void;
  /** Label for the select button */
  selectLabel?: string;
}

export default function PlayerPicker({
  data,
  pool,
  selected = [],
  maxSelect,
  onSelect,
  selectLabel = "Add",
}: Props) {
  const [search, setSearch] = useState("");
  const [expandedTeam, setExpandedTeam] = useState<string | null>(null);

  const allTeams = useMemo(() => {
    if (!data) return [];
    const hitterTeams = pool !== "pitchers" ? Object.keys(data.hitters) : [];
    const pitcherTeams = pool !== "hitters" ? Object.keys(data.pitchers) : [];
    return [...new Set([...hitterTeams, ...pitcherTeams])].sort();
  }, [data, pool]);

  const filteredTeams = useMemo(() => {
    if (!search.trim()) return allTeams;
    const q = search.toLowerCase();
    return allTeams.filter((team) => {
      if (team.toLowerCase().includes(q)) return true;
      const hitters = pool !== "pitchers" ? (data?.hitters[team] ?? []) : [];
      const pitchers = pool !== "hitters" ? (data?.pitchers[team] ?? []) : [];
      return [...hitters, ...pitchers].some((p) =>
        p.Name.toLowerCase().includes(q),
      );
    });
  }, [allTeams, search, data, pool]);

  const playerMatchesSearch = (p: PlayerRow) =>
    !search.trim() || p.Name.toLowerCase().includes(search.toLowerCase());

  if (!data) {
    return (
      <div className="text-gray-500 text-sm text-center py-8">
        Loading players…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Search box */}
      <div className="relative">
        <input
          type="text"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            // Auto-expand teams that match
            if (e.target.value.trim()) setExpandedTeam("__all__");
          }}
          placeholder="Search players or teams…"
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
        />
        {search && (
          <button
            onClick={() => setSearch("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 text-xs"
          >
            ✕
          </button>
        )}
      </div>

      {/* Team accordion list */}
      <div className="space-y-1 max-h-96 overflow-y-auto pr-1">
        {filteredTeams.map((team) => {
          const hPlayers = (pool !== "pitchers" ? (data.hitters[team] ?? []) : []).filter(
            playerMatchesSearch,
          );
          const pPlayers = (pool !== "hitters" ? (data.pitchers[team] ?? []) : []).filter(
            playerMatchesSearch,
          );
          const all: PlayerRow[] = [...hPlayers, ...pPlayers].sort((a, b) =>
            a.Name.localeCompare(b.Name),
          );
          if (all.length === 0) return null;

          const isOpen =
            expandedTeam === team || expandedTeam === "__all__";

          return (
            <div key={team} className="border border-gray-800 rounded-lg overflow-hidden">
              {/* Team header */}
              <button
                onClick={() =>
                  setExpandedTeam(isOpen && expandedTeam !== "__all__" ? null : team)
                }
                className="w-full flex items-center justify-between px-3 py-2 bg-gray-800/60 hover:bg-gray-800 transition-colors text-left"
              >
                <span className="text-sm font-semibold text-gray-200">{team}</span>
                <span className="text-xs text-gray-500">
                  {pool === "both"
                    ? `${hPlayers.length}H / ${pPlayers.length}P`
                    : all.length}{" "}
                  {isOpen ? "▲" : "▼"}
                </span>
              </button>

              {/* Players list */}
              {isOpen && (
                <div className="divide-y divide-gray-800/60">
                  {all.map((player) => {
                    const isSelected = selected.includes(player.Name);
                    const isPitcher = "ERA" in player;
                    return (
                      <div
                        key={player.Name}
                        className={`flex items-center justify-between px-3 py-1.5 text-sm ${
                          isSelected
                            ? "bg-blue-950/40 text-blue-300"
                            : "hover:bg-gray-800/40"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                            isPitcher
                              ? "bg-purple-900/60 text-purple-300"
                              : "bg-green-900/60 text-green-300"
                          }`}>
                            {isPitcher ? "P" : "H"}
                          </span>
                          <span className="truncate text-white">{player.Name}</span>
                          <span className="text-gray-500 text-xs shrink-0">
                            {player.total_z > 0 ? "+" : ""}
                            {player.total_z.toFixed(1)}z
                          </span>
                        </div>
                        <button
                          onClick={() => onSelect(player)}
                          disabled={
                            isSelected ||
                            (maxSelect !== undefined && selected.length >= maxSelect)
                          }
                          className={`ml-2 px-2 py-0.5 rounded text-xs font-medium transition-colors shrink-0 ${
                            isSelected
                              ? "bg-blue-700/50 text-blue-300 cursor-default"
                              : selected.length >= (maxSelect ?? Infinity)
                              ? "bg-gray-700 text-gray-500 cursor-not-allowed"
                              : "bg-blue-700 hover:bg-blue-600 text-white"
                          }`}
                        >
                          {isSelected ? "Added" : selectLabel}
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {filteredTeams.filter(Boolean).length === 0 && (
          <p className="text-gray-500 text-sm text-center py-4">
            No players found for &quot;{search}&quot;
          </p>
        )}
      </div>
    </div>
  );
}

"use client";

import type { PlayerType } from "@/lib/types";

interface ToggleProps {
  value: PlayerType;
  onChange: (v: PlayerType) => void;
}

export default function Toggle({ value, onChange }: ToggleProps) {
  const isHitters = value === "hitters";

  return (
    <div className="inline-flex items-center gap-3 bg-gray-900 border border-gray-700 rounded-full px-5 py-2.5">
      {/* Left label */}
      <button
        onClick={() => onChange("hitters")}
        className={`text-sm font-semibold transition-colors duration-150 ${
          isHitters ? "text-blue-400" : "text-gray-500 hover:text-gray-300"
        }`}
      >
        Hitters
      </button>

      {/* Sliding pill */}
      <button
        onClick={() => onChange(isHitters ? "pitchers" : "hitters")}
        aria-label={`Switch to ${isHitters ? "pitchers" : "hitters"}`}
        className="relative w-11 h-6 rounded-full bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-900 transition-colors"
      >
        <span
          className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-md transition-transform duration-200 ${
            isHitters ? "translate-x-0" : "translate-x-5"
          }`}
        />
      </button>

      {/* Right label */}
      <button
        onClick={() => onChange("pitchers")}
        className={`text-sm font-semibold transition-colors duration-150 ${
          !isHitters ? "text-blue-400" : "text-gray-500 hover:text-gray-300"
        }`}
      >
        Pitchers
      </button>
    </div>
  );
}

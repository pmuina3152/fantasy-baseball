"use client";

import { useApp } from "@/context/AppContext";
import { TIMEFRAME_LABELS, type Timeframe } from "@/lib/types";

const OPTIONS: Timeframe[] = ["season", "last60g", "last25g", "last5g"];

export default function TimeframeSelector() {
  const { timeframe, setTimeframe } = useApp();

  return (
    <div className="flex items-center gap-1 flex-wrap">
      <span className="text-xs text-gray-500 mr-1">Timeframe:</span>
      {OPTIONS.map((opt) => (
        <button
          key={opt}
          onClick={() => setTimeframe(opt)}
          className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
            timeframe === opt
              ? "bg-blue-600 text-white"
              : "bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700"
          }`}
        >
          {TIMEFRAME_LABELS[opt]}
        </button>
      ))}
    </div>
  );
}

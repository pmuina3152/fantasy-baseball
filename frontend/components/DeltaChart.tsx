"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { StatDelta } from "@/lib/types";

interface Props {
  deltas: StatDelta[];
  title?: string;
}

// Custom tooltip
function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const delta = payload[0].value as number;
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="font-semibold text-gray-200 mb-1">{label}</p>
      <p className={delta >= 0 ? "text-emerald-400" : "text-red-400"}>
        {delta >= 0 ? "+" : ""}{delta.toFixed(3)} z
      </p>
      <p className="text-gray-500 mt-0.5">
        {delta >= 0 ? "Team A gains" : "Team A loses"} in this category
      </p>
    </div>
  );
}

export default function DeltaChart({ deltas, title }: Props) {
  if (deltas.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-600 text-sm">
        Select players on both sides to see stat deltas.
      </div>
    );
  }

  const data = deltas.map((d) => ({
    name: d.label,
    delta: d.delta,
    sideA: d.sideA,
    sideB: d.sideB,
  }));

  return (
    <div>
      {title && (
        <h3 className="text-sm font-semibold text-gray-300 mb-3">{title}</h3>
      )}
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#6b7280", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => (v > 0 ? `+${v}` : String(v))}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
          <ReferenceLine y={0} stroke="#374151" strokeWidth={1} />
          <Bar dataKey="delta" radius={[4, 4, 0, 0]} maxBarSize={48}>
            {data.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.delta >= 0 ? "#10b981" : "#ef4444"}
                fillOpacity={Math.abs(entry.delta) < 0.1 ? 0.3 : 0.85}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex items-center justify-center gap-6 mt-2 text-xs text-gray-500">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-emerald-500 inline-block" />
          Team A gains
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-red-500 inline-block" />
          Team A loses
        </span>
      </div>
    </div>
  );
}

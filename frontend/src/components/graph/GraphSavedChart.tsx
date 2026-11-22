// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch (D2 measurement): estimated tokens saved per UTC day.
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { GraphUsage } from "../../api";
import { compact } from "./graphFormat";

const tooltipStyle = {
  backgroundColor: "#1f2937",
  border: "1px solid #374151",
  borderRadius: "8px",
  fontSize: 12,
};

export default function GraphSavedChart({ days }: { days: GraphUsage["days"] }) {
  const points = days.map((d) => ({ date: d.date.slice(5), saved: d.saved_tokens }));
  return (
    <figure className="m-0 flex min-w-0 flex-col rounded-xl border border-gray-800/60 bg-gray-900/40 p-3" data-testid="graph-chart">
      <figcaption className="mb-2 text-sm font-semibold text-gray-100">Tokens saved per day</figcaption>
      <div className="h-36">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: -12 }}>
            <XAxis dataKey="date" tick={{ fill: "#9ca3af", fontSize: 11 }} axisLine={{ stroke: "#374151" }} tickLine={false} minTickGap={16} />
            <YAxis tick={{ fill: "#9ca3af", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={compact} width={44} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "#ffffff0d" }} formatter={(v) => [compact(Number(v ?? 0)), "saved"]} />
            <Bar dataKey="saved" fill="#3b82f6" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

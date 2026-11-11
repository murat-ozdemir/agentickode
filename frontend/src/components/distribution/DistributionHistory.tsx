// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: runs per UTC day, stacked by the "Color by" dimension.
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DistributionDim, RunDistribution } from "../../api";
import { seriesColor } from "./distributionColors";

interface Props {
  data: RunDistribution;
  dim: DistributionDim;
}

const tooltipStyle = {
  backgroundColor: "#1f2937",
  border: "1px solid #374151",
  borderRadius: "8px",
  fontSize: 12,
};

export default function DistributionHistory({ data, dim }: Props) {
  const series = data.groups[dim]
    .map((item, i) => ({ name: item.name, color: seriesColor(dim, item.name, i), count: item.count }))
    .filter((s) => s.count > 0);
  const points = data.days.map((d) => ({ date: d.date.slice(5), ...d.by[dim] }));

  return (
    <figure className="m-0 flex-1 min-w-0 flex flex-col bg-gray-950/60 border border-gray-800/60 rounded-lg p-4" data-testid="distribution-history">
      <div className="flex flex-wrap justify-between items-baseline gap-2 mb-2">
        <figcaption className="text-sm font-semibold text-gray-100">Runs per day</figcaption>
        <ul className="flex flex-wrap gap-3 text-[11px] text-gray-300" aria-label="Legend">
          {series.map((s) => (
            <li key={s.name} className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: s.color }} />
              {s.name}
            </li>
          ))}
        </ul>
      </div>
      {/* grows with the lists beside it; absolute so recharts can measure the flex height */}
      <div className="relative flex-1 min-h-[200px]">
        <div className="absolute inset-0">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={points}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#9ca3af" }} minTickGap={12} />
              <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} width={28} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "#1f2937" }} />
              {series.map((s) => (
                <Bar key={s.name} dataKey={s.name} stackId="runs" fill={s.color} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </figure>
  );
}

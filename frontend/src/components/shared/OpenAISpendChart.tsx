// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: this month's OpenAI spend per UTC day, as on platform.openai.com/usage.
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { OpenAIUsageSummary } from "../../api";

const tooltipStyle = {
  backgroundColor: "#1f2937",
  border: "1px solid #374151",
  borderRadius: "8px",
  fontSize: 12,
};

/** Every day of the month up to the last stored one, days without spend as 0. */
function monthBars(data: OpenAIUsageSummary) {
  const spend = new Map(data.month_days.map((d) => [d.day, d.cost_usd]));
  const last = data.month_days[data.month_days.length - 1]?.day ?? data.month_start;
  const bars = [];
  for (let day = new Date(`${data.month_start}T00:00:00Z`); ; day.setUTCDate(day.getUTCDate() + 1)) {
    const key = day.toISOString().slice(0, 10);
    bars.push({ date: key.slice(8), cost: spend.get(key) ?? 0 });
    if (key >= last) break;
  }
  return bars;
}

export default function OpenAISpendChart({ data }: { data: OpenAIUsageSummary | null }) {
  if (!data?.enabled) return null;
  return (
    <div className="bg-gray-900/50 border border-gray-800/60 rounded-xl p-4" data-testid="openai-spend-chart">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 flex justify-between">
        OpenAI Spend ($)
        <span className="text-gray-300 normal-case" data-testid="openai-month-spend">
          ${data.month_spend_usd.toFixed(2)} this month
        </span>
      </h3>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={monthBars(data)}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#9ca3af" }} />
          <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v) => `$${Number(v).toFixed(2)}`} />
          <Bar dataKey="cost" fill="#ec4899" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

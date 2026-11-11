// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: Dashboard card — how runs split by server, agent, model, difficulty, type, outcome.
import { useEffect, useState } from "react";
import { BarChart3 } from "lucide-react";
import { getRunDistribution } from "../../api";
import type { DistributionDim, DistributionFilter, DistributionRange, RunDistribution } from "../../api";
import DistributionGroup from "./DistributionGroup";
import DistributionHistory from "./DistributionHistory";

interface Props {
  onSelect: (filter: DistributionFilter) => void;
}

const COLOR_BY: [DistributionDim, string][] = [
  ["agent", "Agent"],
  ["server", "Server"],
  ["model", "Model"],
  ["difficulty", "Difficulty"],
  ["type", "Type"],
];
const RANGES: [DistributionRange, string][] = [["7d", "7d"], ["30d", "30d"], ["all", "All"]];
const GROUPS: [DistributionDim, string, string][] = [
  ["server", "Server", "runs · ok"],
  ["agent", "Agent", "runs"],
  ["model", "Model", "runs"],
  ["difficulty", "Difficulty", "label"],
  ["type", "Run type", "trigger"],
  ["outcome", "Outcome", "runs"],
];

function sinceLabel(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

function Pills<T extends string>({ label, options, value, onChange }: {
  label: string; options: [T, string][]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-0.5 bg-gray-950 border border-gray-800 rounded-lg p-0.5">
      {label === "Color by" && <span className="text-[11px] text-gray-400 px-2">Color by</span>}
      {options.map(([key, text]) => (
        <button
          key={key}
          type="button"
          aria-pressed={value === key}
          onClick={() => onChange(key)}
          className={`rounded-md px-2.5 py-1.5 text-xs ${value === key ? "bg-gray-800 text-gray-50 font-semibold" : "text-gray-400 hover:text-gray-200"}`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export default function TaskDistributionCard({ onSelect }: Props) {
  const [dim, setDim] = useState<DistributionDim>("agent");
  const [range, setRange] = useState<DistributionRange>("all");
  const [data, setData] = useState<RunDistribution | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getRunDistribution(range)
      .then((d) => { if (live) { setData(d); setError(null); } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : "Could not load the distribution"); });
    return () => { live = false; };
  }, [range]);

  return (
    <section aria-labelledby="td-title" className="bg-gray-900/50 border border-gray-800/60 rounded-xl p-5 mb-6 flex flex-col gap-4" data-testid="task-distribution">
      <div className="flex flex-wrap justify-between items-center gap-3">
        <div className="flex items-center gap-2.5">
          <BarChart3 className="w-5 h-5 text-blue-400" aria-hidden="true" />
          <h2 id="td-title" className="m-0 text-base font-semibold">Task Distribution</h2>
          {data && (
            <span className="text-xs text-gray-400" data-testid="distribution-total">
              {data.total} runs since {sinceLabel(data.since)}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Pills label="Color by" options={COLOR_BY} value={dim} onChange={setDim} />
          <Pills label="Time range" options={RANGES} value={range} onChange={setRange} />
        </div>
      </div>
      {error && <p className="m-0 text-sm text-red-400">Could not load the distribution: {error}</p>}
      {!data && !error && <p className="m-0 text-sm text-gray-400">Loading…</p>}
      {data && (
        <div className="flex flex-wrap gap-5 items-stretch">
          <div className="flex flex-[1_1_440px] min-w-0">
            <DistributionHistory data={data} dim={dim} />
          </div>
          <div className="flex-[2_1_620px] min-w-0 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-x-6 gap-y-5 content-start">
            {GROUPS.map(([key, title, hint]) => (
              <DistributionGroup
                key={key}
                dim={key}
                title={title}
                hint={hint}
                items={data.groups[key]}
                limit={key === "model" ? 5 : undefined}
                onSelect={(value) => onSelect({ dim: key, value, range })}
              />
            ))}
          </div>
        </div>
      )}
      <p className="m-0 text-[11px] text-gray-400">
        Counts come from task_runs and agent_invocations. Click a row to filter the Runs list.
      </p>
    </section>
  );
}

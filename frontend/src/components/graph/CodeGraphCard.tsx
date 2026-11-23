// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch (D2 measurement): Dashboard card — how much the agents use the code graph and
// the tokens it saves them (an estimate: the pointed-at files read whole, minus what was sent).
import { useEffect, useState } from "react";
import { Share2 } from "lucide-react";
import { getGraphUsage } from "../../api";
import type { DistributionRange, GraphUsage } from "../../api";
import GraphSavedChart from "./GraphSavedChart";
import GraphWorkerTable from "./GraphWorkerTable";
import { compact, pct, savedTone } from "./graphFormat";

const RANGES: [DistributionRange, string][] = [["7d", "7d"], ["30d", "30d"], ["all", "All"]];

function Tile({ label, value, note, tone = "" }: { label: string; value: string; note: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-gray-800/60 bg-gray-900/40 p-3">
      <div className="text-[11px] uppercase tracking-wider text-gray-400">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${tone}`}>{value}</div>
      <div className="text-[11px] text-gray-500">{note}</div>
    </div>
  );
}

function PerCallTile({ rt }: { rt: GraphUsage["run_tokens"] }) {
  const value = rt.tokens_per_call == null ? "–" : compact(rt.tokens_per_call);
  const note = rt.turns_per_call == null ? `${rt.calls} calls` : `${rt.turns_per_call} turns · ${rt.calls} calls`;
  return <Tile label="Tokens per call" value={value} note={note} />;
}

function Tiles({ data }: { data: GraphUsage }) {
  const t = data.totals;
  const share = data.total_runs ? Math.round((100 * t.runs) / data.total_runs) : 0;
  const agents = Object.entries(data.agents).map(([a, n]) => `${a} ${n}`).join(", ");
  const shellReads = data.run_tokens?.shell_reads ?? 0;
  const sent = `sent ${compact(t.returned_chars)} of ${compact(t.full_chars)} chars`;
  const shareNote = shellReads ? `${sent} · ${shellReads} shell reads (Codex)` : sent;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5" data-testid="graph-tiles">
      <Tile label="Runs using graph" value={`${t.runs} / ${data.total_runs}`} note={agents ? `${share}% · ${agents}` : `${share}%`} />
      <Tile label="Graph calls" value={String(t.calls)} note={t.runs ? `${(t.calls / t.runs).toFixed(1)} per run` : "no runs yet"} />
      <Tile label="Tokens saved" value={compact(t.saved_tokens)} note={`≈ $${t.saved_usd.toFixed(2)} at input price`} tone={savedTone(t.saved_tokens)} />
      <Tile label="Read savings" value={pct(t.saved_pct)} note={shareNote} tone={savedTone(t.saved_pct)} />
      {data.run_tokens && <PerCallTile rt={data.run_tokens} />}
    </div>
  );
}

export default function CodeGraphCard() {
  const [range, setRange] = useState<DistributionRange>("7d");
  const [data, setData] = useState<GraphUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getGraphUsage(range)
      .then((d) => { if (live) { setData(d); setError(null); } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : "Could not load graph usage"); });
    return () => { live = false; };
  }, [range]);

  return (
    <section aria-labelledby="graph-title" className="flex flex-col gap-4 rounded-xl border border-gray-800/60 bg-gray-900/50 p-5" data-testid="code-graph-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Share2 className="h-5 w-5 text-blue-400" aria-hidden="true" />
          <h2 id="graph-title" className="m-0 text-base font-semibold">Code graph</h2>
        </div>
        <div role="group" aria-label="Time range" className="flex rounded-lg border border-gray-800 p-0.5 text-xs">
          {RANGES.map(([key, text]) => (
            <button
              key={key}
              type="button"
              aria-pressed={range === key}
              onClick={() => setRange(key)}
              className={`rounded-md px-2.5 py-1 ${range === key ? "bg-gray-800 font-semibold text-white" : "text-gray-400 hover:text-gray-200"}`}
            >
              {text}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="m-0 text-sm text-red-400">Could not load graph usage: {error}</p>}
      {!data && !error && <p className="m-0 text-sm text-gray-400">Loading…</p>}
      {data && (
        <>
          <Tiles data={data} />
          <div className="grid flex-1 gap-4 xl:grid-cols-[1.2fr_1fr]">
            <GraphSavedChart days={data.days} />
            <GraphWorkerTable workers={data.workers} totals={data.totals} />
          </div>
        </>
      )}
    </section>
  );
}

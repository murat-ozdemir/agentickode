// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch (D2 measurement): code graph use of one agent call (metadata_.graph):
// calls per tool, fallback_rg past the budget, failed calls and the estimated saving.
import { compact, graphOf, pct } from "../graph/graphFormat";

export default function InvocationGraphNote({ metadata }: { metadata: Record<string, unknown> | null | undefined }) {
  const g = graphOf(metadata);
  if (!g) return null;
  const tools = Object.entries(g.tools).sort((a, b) => b[1] - a[1]);
  const share = g.full_chars > 0 ? Math.max(0, Math.round((100 * (g.full_chars - g.returned_chars)) / g.full_chars)) : null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-400" data-testid="invocation-graph">
      <span className="font-medium text-gray-300">Code graph: {g.calls} calls</span>
      {tools.map(([tool, n]) => (
        <span key={tool} className="rounded bg-gray-800 px-1.5 py-0.5 font-mono text-gray-300">
          {tool} {n}
        </span>
      ))}
      {g.over_budget > 0 && <span className="text-amber-400">{g.over_budget} over budget</span>}
      {g.errors > 0 && <span className="text-red-400">{g.errors} failed</span>}
      <span className="text-emerald-400">
        saved ≈ {compact(g.saved_tokens)} tokens ({pct(share)})
      </span>
      <span className="text-gray-500">
        sent {compact(g.returned_chars)} of {compact(g.full_chars)} chars in {g.files} files
      </span>
    </div>
  );
}

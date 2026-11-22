// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch (D2 measurement): graph use and savings per worker, with a total row.
import type { GraphSums, GraphWorker } from "../../api";
import { compact, pct } from "./graphFormat";

interface Props {
  workers: GraphWorker[];
  totals: GraphSums;
}

function Row({ name, s, total }: { name: string; s: GraphSums; total?: boolean }) {
  return (
    <tr className={`border-t ${total ? "border-gray-700 font-semibold" : "border-gray-800"}`}>
      <td className="py-1.5">{name}</td>
      <td className="text-right">{s.runs}</td>
      <td className="text-right">{s.calls}</td>
      <td className="text-right">{compact(s.saved_tokens)}</td>
      <td className="text-right text-emerald-400">{pct(s.saved_pct)}</td>
    </tr>
  );
}

export default function GraphWorkerTable({ workers, totals }: Props) {
  return (
    <div className="min-w-0 rounded-xl border border-gray-800/60 bg-gray-900/40 p-3" data-testid="graph-workers">
      <div className="mb-2 text-sm font-semibold text-gray-100">By worker</div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[11px] uppercase tracking-wider text-gray-500">
            <th className="pb-1 text-left font-medium">Worker</th>
            <th className="pb-1 text-right font-medium">Runs</th>
            <th className="pb-1 text-right font-medium">Calls</th>
            <th className="pb-1 text-right font-medium">Saved</th>
            <th className="pb-1 text-right font-medium">%</th>
          </tr>
        </thead>
        <tbody className="text-gray-200">
          {workers.map((w) => <Row key={w.name} name={w.name} s={w} />)}
          {workers.length > 1 && <Row name="Total" s={totals} total />}
        </tbody>
      </table>
    </div>
  );
}

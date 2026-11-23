// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: records already in mem0 that a proposal resembles; one can be picked to replace.
import type { SimilarMemory } from "../../api";

interface Props {
  records: SimilarMemory[];
  replaces: string | null;
  // undefined: read-only (decided proposals)
  onReplacesChange?: (id: string | null) => void;
}

export default function SimilarRecords({ records, replaces, onReplacesChange }: Props) {
  if (records.length === 0) return null;
  return (
    <div data-testid="similar-records" className="space-y-1.5">
      <p className="text-xs text-gray-400">Similar records already in memory</p>
      {records.map((r) => {
        const replaced = r.id === replaces;
        return (
          <div
            key={r.id}
            className={`flex items-start gap-2 rounded border px-2 py-1.5 text-xs ${
              replaced ? "border-amber-700 bg-amber-900/20" : "border-gray-800 bg-gray-950"
            }`}
          >
            <span className="shrink-0 text-gray-500 font-mono">
              {r.similarity !== undefined ? `${Math.round(r.similarity * 100)}%` : "—"}
            </span>
            {r.kind && <span className="shrink-0 text-gray-500">{r.kind}</span>}
            <span className="flex-1 text-gray-300">{r.text}</span>
            {replaced && <span className="shrink-0 text-amber-300">Will be replaced</span>}
            {onReplacesChange && (
              <button
                onClick={() => onReplacesChange(replaced ? null : r.id)}
                className="shrink-0 text-blue-400 hover:underline"
              >
                {replaced ? "Add as new instead" : "Replace this"}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch (loop efficiency item 7): the PR's chain notebook, as every agent of the chain sees it.
import { useEffect, useState } from "react";
import { BookOpen, ChevronDown, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { getRunNotebook } from "../../api";
import type { NotebookKind, RunNotebook } from "../../api";

const LABELS: Record<NotebookKind, { label: string; className: string }> = {
  decision: { label: "Decision", className: "bg-emerald-900/40 text-emerald-300" },
  question: { label: "Question", className: "bg-amber-900/40 text-amber-300" },
  answer: { label: "Answer", className: "bg-sky-900/40 text-sky-300" },
  run: { label: "Run", className: "bg-gray-700/50 text-gray-300" },
  ci: { label: "CI", className: "bg-purple-900/40 text-purple-300" },
};

interface Props {
  runId: number;
}

export default function ChainNotebookPanel({ runId }: Props) {
  const [notebook, setNotebook] = useState<RunNotebook | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    let active = true;
    getRunNotebook(runId)
      .then((data) => { if (active) setNotebook(data); })
      .catch((err) => console.warn("Chain notebook unavailable", err));
    return () => { active = false; };
  }, [runId]);

  if (!notebook || notebook.entries.length === 0) return null;

  return (
    <div
      className="bg-gray-900/50 border border-gray-800/60 rounded-xl p-5 mb-6"
      data-testid="chain-notebook"
    >
      <button
        className="w-full flex items-center gap-2 text-left mb-3"
        onClick={() => setCollapsed((v) => !v)}
      >
        <BookOpen className="w-4 h-4 text-emerald-400 flex-shrink-0" />
        <h2 className="text-lg font-semibold flex-1">Chain notebook</h2>
        <span className="text-xs text-gray-500 mr-2">
          PR #{notebook.pr_number} · {notebook.entries.length} entries
        </span>
        {collapsed ? (
          <ChevronRight className="w-4 h-4 text-gray-500" />
        ) : (
          <ChevronDown className="w-4 h-4 text-gray-500" />
        )}
      </button>
      {!collapsed && (
        <ul className="space-y-2">
          {notebook.entries.map((e, i) => {
            const kind = LABELS[e.kind] ?? LABELS.run;
            return (
              <li key={`${e.at}-${i}`} className="flex gap-2 text-sm">
                <span className={`text-[10px] h-fit px-1.5 py-0.5 rounded font-medium ${kind.className}`}>
                  {kind.label}
                </span>
                <span className="flex-1 whitespace-pre-wrap text-gray-300">{e.text}</span>
                {e.run_id != null && (
                  <Link to={`/runs/${e.run_id}`} className="text-xs text-blue-400 hover:underline">
                    #{e.run_id}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

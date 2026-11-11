// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: one list of the Task Distribution card; a row filters the Runs list.
import { useState } from "react";
import type { DistributionDim, DistributionItem } from "../../api";
import { listColor } from "./distributionColors";

interface Props {
  dim: DistributionDim;
  title: string;
  hint: string;
  items: DistributionItem[];
  limit?: number;
  onSelect: (value: string) => void;
}

const LABELS: Record<string, string> = { fix: "fix (PR comment)" };

export default function DistributionGroup({ dim, title, hint, items, limit, onSelect }: Props) {
  const [expanded, setExpanded] = useState(false);
  const max = Math.max(0, ...items.map((i) => i.count));
  const shown = limit && !expanded ? items.slice(0, limit) : items;
  const hidden = items.slice(shown.length);

  return (
    <section className="flex flex-col gap-1.5" data-testid={`distribution-group-${dim}`}>
      <div className="flex justify-between items-baseline">
        <h3 className="m-0 text-[11px] font-semibold uppercase tracking-wider text-gray-400">{title}</h3>
        <span className="text-[11px] text-gray-400">{hint}</span>
      </div>
      {shown.map((item, i) => (
        <button
          key={item.name}
          type="button"
          onClick={() => onSelect(item.name)}
          disabled={item.count === 0}
          title={item.count ? `Show these runs in the list below` : undefined}
          className="flex flex-col gap-1 text-left rounded px-1 -mx-1 py-0.5 hover:bg-gray-800/60 disabled:hover:bg-transparent disabled:cursor-default"
        >
          <span className="flex w-full justify-between gap-2 text-xs">
            <span className="text-gray-200 truncate">{LABELS[item.name] ?? item.name}</span>
            <span className="text-gray-100 tabular-nums whitespace-nowrap">
              {item.count}
              {item.ok_pct != null && <span className="text-gray-400"> · {item.ok_pct}%</span>}
            </span>
          </span>
          <span className="block w-full h-[5px] bg-gray-800 rounded overflow-hidden">
            <span
              className="block h-full rounded"
              style={{
                width: `${max ? Math.max(item.count ? 2 : 0, Math.round((item.count / max) * 100)) : 0}%`,
                background: listColor(dim, item.name, i),
              }}
            />
          </span>
        </button>
      ))}
      {(hidden.length > 0 || expanded) && limit && items.length > limit && (
        <button type="button" onClick={() => setExpanded(!expanded)} className="self-start text-[11px] text-blue-300 hover:text-blue-200">
          {expanded
            ? "Show less"
            : `+${hidden.length} more (${hidden.reduce((n, i) => n + i.count, 0)} runs)`}
        </button>
      )}
    </section>
  );
}

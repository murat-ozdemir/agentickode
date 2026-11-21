// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: one limit window (5h / weekly) with a pace tick and the reset countdown.
import type { QuotaWindow } from "../../api";
import { pacePercent, toneOf, untilText } from "./quotaFormat";

const FILL = { ok: "bg-blue-500", warn: "bg-amber-500", hit: "bg-red-500" } as const;
const TEXT = { ok: "text-gray-200", warn: "text-amber-400", hit: "text-red-400" } as const;

export default function QuotaBar({ window: w }: { window: QuotaWindow }) {
  const tone = toneOf(w);
  const pace = pacePercent(w);
  const used = Math.min(100, Math.max(0, w.used_percent));
  const resetTitle = w.resets_at
    ? `Resets ${new Date(w.resets_at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" })}`
    : undefined;

  return (
    <div className="flex items-center gap-2 text-xs" data-testid={`quota-bar-${w.key}`} title={resetTitle}>
      <span className="w-12 shrink-0 truncate text-gray-400" title={w.scope ? `${w.label} only` : undefined}>
        {w.label}
      </span>
      <div className="relative h-2 flex-1 rounded-full bg-gray-800">
        <div
          className={`h-2 rounded-full ${FILL[tone]}`}
          style={{ width: `${used}%` }}
          data-testid="quota-fill"
          data-tone={tone}
        />
        {pace != null && (
          <div
            className="absolute -top-0.5 h-3 w-px bg-gray-300/70"
            style={{ left: `${pace}%` }}
            title="Even pace for this window"
            data-testid="quota-pace"
          />
        )}
      </div>
      <span className={`w-10 shrink-0 text-right font-medium ${TEXT[tone]}`}>
        {Math.round(w.used_percent)}%
      </span>
      <span className="w-16 shrink-0 text-right text-gray-500" data-testid="quota-reset">
        {w.resets_at ? untilText(w.resets_at) : "—"}
      </span>
    </div>
  );
}

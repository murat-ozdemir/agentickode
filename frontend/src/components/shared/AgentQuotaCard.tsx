// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: one subscription account — who it is, its limit windows, the workers on it.
import { AlertTriangle } from "lucide-react";
import type { QuotaAccount } from "../../api";
import QuotaBar from "./QuotaBar";
import { providerLabel, shortTime, untilText } from "./quotaFormat";

/** Earliest reset among the windows that are at their limit. */
function nextRelease(account: QuotaAccount): string | null {
  const times = account.windows
    .filter((w) => w.used_percent >= 100 && w.resets_at)
    .map((w) => w.resets_at as string)
    .sort();
  return times[0] ?? null;
}

export default function AgentQuotaCard({ account }: { account: QuotaAccount }) {
  const { email, plan, org_name: org, windows, workers, error, observed_at: observed } = account;
  const hit = account.limit_reached;
  const release = hit ? nextRelease(account) : null;

  return (
    <div
      className={`border rounded-xl p-4 space-y-3 ${
        hit ? "bg-red-500/10 border-red-500/60" : "bg-gray-900/50 border-gray-800/60"
      }`}
      data-testid="quota-account"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-100">
            {providerLabel(account.provider)}
            {plan && (
              <span
                className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-gray-300"
                data-testid="quota-plan"
              >
                {plan}
              </span>
            )}
          </div>
          <div
            className="truncate text-xs text-gray-400"
            title={[email, org].filter(Boolean).join(" · ")}
            data-testid="quota-email"
          >
            {email ?? "Unknown account"}
            {org && <span className="text-gray-500"> · {org}</span>}
          </div>
        </div>
        {hit && (
          <span className="shrink-0 text-xs font-medium text-red-400" data-testid="quota-hit">
            Limit hit{release ? ` · ${untilText(release)}` : ""}
          </span>
        )}
      </div>

      <div className="space-y-1.5">
        {windows.map((w) => (
          <QuotaBar key={w.key} window={w} />
        ))}
        {windows.length === 0 && <div className="text-xs text-gray-500">No usage data yet</div>}
      </div>

      <div className="flex flex-wrap gap-1">
        {workers.map((w) => (
          <span
            key={`${w.server_id}-${w.user}`}
            className="rounded bg-gray-800/80 px-1.5 py-0.5 text-[11px] text-gray-300"
            data-testid="quota-worker"
          >
            {w.server_name}
            <span className="text-gray-500">/{w.user}</span>
          </span>
        ))}
      </div>

      {error && (
        <div
          className="flex items-center gap-1 text-[11px] text-amber-400"
          title={error}
          data-testid="quota-error"
        >
          <AlertTriangle className="h-3 w-3 shrink-0" />
          <span className="truncate">
            {error}
            {observed && ` — numbers from ${shortTime(observed)}`}
          </span>
        </div>
      )}
    </div>
  );
}

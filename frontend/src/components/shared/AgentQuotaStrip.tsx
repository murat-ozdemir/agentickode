// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: Dashboard panel with one card per agent subscription account.
import { AlertTriangle, Gauge, RefreshCw } from "lucide-react";
import useAgentQuotas from "../../hooks/useAgentQuotas";
import AgentQuotaCard from "./AgentQuotaCard";
import { shortTime } from "./quotaFormat";

export default function AgentQuotaStrip() {
  const { data, error, syncing, refresh } = useAgentQuotas();
  const accounts = data?.accounts ?? [];
  const problems = [
    ...(error ? [error] : []),
    ...(data?.errors ?? []).map((e) => `${e.server_name}: ${e.error}`),
  ];

  return (
    <section
      aria-labelledby="quota-title"
      className="bg-gray-900/50 border border-gray-800/60 rounded-xl p-5 mb-6 flex flex-col gap-4"
      data-testid="agent-quota-strip"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Gauge className="w-5 h-5 text-blue-400" aria-hidden="true" />
          <h2 id="quota-title" className="m-0 text-base font-semibold">
            Subscription limits
          </h2>
          {problems.length > 0 && (
            <span
              className="flex items-center gap-1 text-xs text-amber-400"
              title={problems.join("\n")}
              data-testid="quota-problems"
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              {problems.length === 1 ? "1 issue" : `${problems.length} issues`}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          {data?.last_sync_at && (
            <span data-testid="quota-updated">Updated {shortTime(data.last_sync_at)}</span>
          )}
          <button
            onClick={refresh}
            disabled={syncing}
            title="Check the workers now"
            aria-label="Refresh subscription limits"
            className="p-1 text-gray-500 hover:text-white rounded disabled:opacity-40"
            data-testid="quota-sync"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>
      {accounts.length === 0 ? (
        <div className="text-xs text-gray-500" data-testid="quota-empty">
          {data ? "No agent subscriptions found on the workers yet." : "Loading…"}
        </div>
      ) : (
        // Equal-width cards: 2 accounts split the row in half, 3 in thirds; no empty slot.
        <div className="grid gap-4 grid-cols-[repeat(auto-fit,minmax(min(100%,320px),1fr))]">
          {accounts.map((a) => (
            <AgentQuotaCard key={a.id} account={a} />
          ))}
        </div>
      )}
    </section>
  );
}

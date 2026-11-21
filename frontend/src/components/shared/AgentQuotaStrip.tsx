// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: Dashboard strip with one card per agent subscription account.
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
    <section className="space-y-2" data-testid="agent-quota-strip">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-gray-400">
          <Gauge className="h-4 w-4" />
          Subscription limits
          {problems.length > 0 && (
            <span
              className="flex items-center gap-1 normal-case tracking-normal text-amber-400"
              title={problems.join("\n")}
              data-testid="quota-problems"
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              {problems.length === 1 ? "1 issue" : `${problems.length} issues`}
            </span>
          )}
        </h2>
        <div className="flex items-center gap-2 text-[11px] text-gray-500">
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
        <div
          className="rounded-xl border border-gray-800/60 bg-gray-900/50 p-4 text-xs text-gray-500"
          data-testid="quota-empty"
        >
          {data ? "No agent subscriptions found on the workers yet." : "Loading…"}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {accounts.map((a) => (
            <AgentQuotaCard key={a.id} account={a} />
          ))}
        </div>
      )}
    </section>
  );
}

// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: OpenAI credit left (hand-entered credits minus Costs API spend), quota alert.
import { useState } from "react";
import { Plus, RefreshCw, Wallet } from "lucide-react";
import type { OpenAIUsage } from "../../hooks/useOpenAIUsage";
import OpenAICreditsModal from "./OpenAICreditsModal";

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" });

/** Time only for today, day/month and time otherwise: the card is narrow. */
const short = (iso: string) => {
  const d = new Date(iso);
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === new Date().toDateString()) return time;
  return `${d.toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit" })} ${time}`;
};

const iconButton = "p-1 text-gray-500 hover:text-white rounded disabled:opacity-40";

export default function OpenAIBalanceCard({ usage }: { usage: OpenAIUsage }) {
  const { data, error, syncing, reload, refresh } = usage;
  const [modalOpen, setModalOpen] = useState(false);

  const alert = data?.alert;
  const remaining = data?.remaining_usd ?? null;
  const red = alert != null || (remaining != null && remaining <= 0);
  const problem = alert
    ? `Out of credit: ${alert.source} got ${alert.code} (${when(alert.at)}). Add a credit entry after topping up.`
    : data?.sync_error ?? error;

  let note = "";
  if (data && !data.enabled) note = "OPENAI_ADMIN_KEY not set";
  else if (data && remaining == null) note = "Add the billing balance";
  else if (data?.last_sync_at) note = `Updated ${short(data.last_sync_at)}`;

  return (
    <div
      className={`border rounded-xl p-4 flex items-center gap-3 ${
        alert ? "bg-red-500/10 border-red-500/70" : "bg-gray-900/50 border-gray-800/60"
      }`}
      title={problem ?? undefined}
      data-testid="openai-balance-card"
    >
      <div className={red ? "text-red-400" : "text-emerald-400"}><Wallet className="w-5 h-5" /></div>
      <div className="min-w-0 flex-1">
        <div className="text-xs text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
          OpenAI Balance
          {problem && (
            <span className="w-1.5 h-1.5 rounded-full bg-red-500" data-testid="openai-problem" />
          )}
        </div>
        <div
          className={`text-lg font-semibold ${red ? "text-red-400" : "text-gray-100"}`}
          data-testid="openai-remaining"
        >
          {remaining == null ? "—" : `$${remaining.toFixed(2)}`}
        </div>
        {note && <div className="text-[11px] text-gray-500 truncate" data-testid="openai-note">{note}</div>}
      </div>
      <div className="flex flex-col self-start">
        <button
          onClick={refresh}
          disabled={syncing || !data?.enabled}
          title="Refresh"
          aria-label="Refresh"
          className={iconButton}
          data-testid="openai-sync"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${syncing ? "animate-spin" : ""}`} />
        </button>
        <button
          onClick={() => setModalOpen(true)}
          title="Add credit"
          aria-label="Add credit"
          className={iconButton}
          data-testid="openai-add-credit"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>
      {modalOpen && <OpenAICreditsModal onClose={() => setModalOpen(false)} onChanged={reload} />}
    </div>
  );
}

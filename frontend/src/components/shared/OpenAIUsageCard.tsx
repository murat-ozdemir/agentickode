// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: OpenAI API spend of mem0 + memory proposals, credit balance and quota alert.
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Plus, RefreshCw, Wallet } from "lucide-react";
import { getOpenAIUsageSummary, syncOpenAIUsage, type OpenAIUsageSummary } from "../../api";
import OpenAICreditsModal from "./OpenAICreditsModal";

const POLL_MS = 60_000;

const usd = (n: number) => `$${n.toFixed(2)}`;

const when = (iso: string) =>
  new Date(iso).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });

function Figure({ label, value, testId, tone = "text-white" }: {
  label: string;
  value: string;
  testId: string;
  tone?: string;
}) {
  return (
    <div>
      <div className={`text-2xl font-bold ${tone}`} data-testid={testId}>{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </div>
  );
}

export default function OpenAIUsageCard() {
  const [data, setData] = useState<OpenAIUsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await getOpenAIUsageSummary());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const refresh = async () => {
    setSyncing(true);
    try {
      setData(await syncOpenAIUsage());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSyncing(false);
    }
  };

  const alert = data?.alert;
  const low = data?.remaining_usd != null && data.remaining_usd <= 0;
  const border = alert ? "border-red-500/70 bg-red-500/10" : "border-gray-800/60 bg-gray-900/40";

  return (
    <div className={`border rounded-xl p-4 mb-6 ${border}`} data-testid="openai-usage-card">
      <div className="flex items-center justify-between gap-3 mb-3">
        <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
          <Wallet className="w-4 h-4 text-emerald-400" />
          OpenAI API (mem0 + hafıza önerileri)
        </h2>
        <div className="flex gap-2">
          <button
            onClick={refresh}
            disabled={syncing || !data?.enabled}
            data-testid="openai-sync"
            className="px-2.5 py-1 text-xs text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg disabled:opacity-40 flex items-center gap-1"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${syncing ? "animate-spin" : ""}`} />
            Yenile
          </button>
          <button
            onClick={() => setModalOpen(true)}
            data-testid="openai-add-credit"
            className="px-2.5 py-1 text-xs text-white bg-blue-600 hover:bg-blue-500 rounded-lg flex items-center gap-1"
          >
            <Plus className="w-3.5 h-3.5" />
            Kredi ekle
          </button>
        </div>
      </div>

      {alert && (
        <div className="flex items-start gap-2 text-sm text-red-300 mb-3" data-testid="openai-alert">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>
            OpenAI kredisi bitti: {alert.source} çağrısı <code>{alert.code}</code> döndü ({when(alert.at)}).
            Kredi yükleyip buraya girince uyarı kalkar.
          </span>
        </div>
      )}

      {data && (
        <div className="grid grid-cols-3 gap-3">
          <Figure label="Bu ay harcama" value={usd(data.month_spend_usd)} testId="openai-month-spend" />
          <Figure label="Yüklenen kredi" value={usd(data.credits_total_usd)} testId="openai-credits" />
          <Figure
            label={data.first_credit_on ? `Kalan (${data.first_credit_on} itibarıyla)` : "Kalan"}
            value={data.remaining_usd == null ? "—" : usd(data.remaining_usd)}
            testId="openai-remaining"
            tone={low || alert ? "text-red-400" : "text-emerald-400"}
          />
        </div>
      )}

      <div className="text-xs text-gray-500 mt-3 space-y-0.5">
        {data && !data.enabled && (
          <p data-testid="openai-disabled">
            OPENAI_ADMIN_KEY tanımlı değil; harcama OpenAI'dan okunamıyor.
          </p>
        )}
        {data?.enabled && data.remaining_usd == null && (
          <p>Kalanı görmek için faturalama sayfasındaki bakiyeyi "Kredi ekle" ile ilk kayıt olarak gir.</p>
        )}
        {data?.last_sync_at && <p data-testid="openai-last-sync">Son güncelleme: {when(data.last_sync_at)}</p>}
        {data?.sync_error && (
          <p className="text-red-400" data-testid="openai-sync-error">Senkron hatası: {data.sync_error}</p>
        )}
        {error && <p className="text-red-400">{error}</p>}
      </div>

      {modalOpen && <OpenAICreditsModal onClose={() => setModalOpen(false)} onChanged={load} />}
    </div>
  );
}

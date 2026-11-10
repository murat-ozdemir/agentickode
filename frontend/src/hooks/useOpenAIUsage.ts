// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: OpenAI spend summary shared by the Dashboard balance card and spend chart.
import { useCallback, useEffect, useState } from "react";
import { getOpenAIUsageSummary, syncOpenAIUsage, type OpenAIUsageSummary } from "../api";

const POLL_MS = 60_000;

export interface OpenAIUsage {
  data: OpenAIUsageSummary | null;
  error: string | null;
  syncing: boolean;
  reload: () => Promise<void>;
  refresh: () => Promise<void>;
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function useOpenAIUsage(): OpenAIUsage {
  const [data, setData] = useState<OpenAIUsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const reload = useCallback(async () => {
    try {
      setData(await getOpenAIUsageSummary());
      setError(null);
    } catch (e) {
      setError(message(e));
    }
  }, []);

  useEffect(() => {
    reload();
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [reload]);

  const refresh = useCallback(async () => {
    setSyncing(true);
    try {
      setData(await syncOpenAIUsage());
      setError(null);
    } catch (e) {
      setError(message(e));
    } finally {
      setSyncing(false);
    }
  }, []);

  return { data, error, syncing, reload, refresh };
}

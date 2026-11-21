// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: subscription limits for the Dashboard strip; reloads the stored readings
// every minute (the backend probes the workers every 10) and probes on demand.
import { useCallback, useEffect, useState } from "react";
import { getAgentQuotas, syncAgentQuotas, type AgentQuotaSummary } from "../api";

const POLL_MS = 60_000;

export interface AgentQuotas {
  data: AgentQuotaSummary | null;
  error: string | null;
  syncing: boolean;
  refresh: () => Promise<void>;
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function useAgentQuotas(): AgentQuotas {
  const [data, setData] = useState<AgentQuotaSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const reload = useCallback(async () => {
    try {
      setData(await getAgentQuotas());
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
      setData(await syncAgentQuotas());
      setError(null);
    } catch (e) {
      setError(message(e));
    } finally {
      setSyncing(false);
    }
  }, []);

  return { data, error, syncing, refresh };
}

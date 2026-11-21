// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: 5-hour / weekly limits of the agent subscription accounts on the workers.
import { get, post } from "./client";

export interface QuotaWindow {
  key: string;
  label: string;
  minutes: number | null;
  used_percent: number;
  resets_at: string | null;
  /** Model the limit applies to; null/absent = the whole account. */
  scope?: string | null;
}

/** Usage credits bought on top of the subscription (Claude extra usage). */
export interface QuotaCredits {
  enabled: boolean;
  used: number | null;
  limit: number | null;
  balance: number | null;
  currency: string | null;
  used_percent: number | null;
  limit_reached: boolean;
}

export interface QuotaWorker {
  server_id: number;
  server_name: string;
  user: string;
}

export interface QuotaAccount {
  id: number;
  provider: string;
  email: string | null;
  plan: string | null;
  org_name: string | null;
  windows: QuotaWindow[];
  limit_reached: boolean;
  credits: QuotaCredits | null;
  workers: QuotaWorker[];
  error: string | null;
  observed_at: string | null;
  checked_at: string | null;
}

export interface AgentQuotaSummary {
  accounts: QuotaAccount[];
  last_sync_at: string | null;
  errors: { server_name: string; error: string }[];
}

const PATH = "/bimetri/agent-quotas";

export const getAgentQuotas = () => get<AgentQuotaSummary>(PATH);

export const syncAgentQuotas = () => post<AgentQuotaSummary>(`${PATH}/sync`);

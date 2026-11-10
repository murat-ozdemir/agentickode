// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: OpenAI API spend (Costs API), hand-entered credits and the quota alert.
import { BASE, get, httpDelete, post } from "./client";

export interface OpenAIQuotaAlert {
  code: string;
  source: string;
  at: string;
}

export interface OpenAIDailySpend {
  day: string;
  cost_usd: number;
}

export interface OpenAIUsageSummary {
  enabled: boolean;
  month_start: string;
  month_spend_usd: number;
  month_days: OpenAIDailySpend[];
  credits_total_usd: number;
  first_credit_on: string | null;
  spent_since_first_credit_usd: number | null;
  remaining_usd: number | null;
  last_sync_at: string | null;
  sync_error: string | null;
  alert: OpenAIQuotaAlert | null;
}

export interface OpenAICredit {
  id: number;
  amount_usd: number;
  credited_on: string;
  created_at: string | null;
}

export interface OpenAICreditInput {
  amount_usd: string;
  credited_on: string;
}

const PATH = "/bimetri/openai";

export const getOpenAIUsageSummary = () => get<OpenAIUsageSummary>(`${PATH}/summary`);

export const syncOpenAIUsage = () => post<OpenAIUsageSummary>(`${PATH}/sync`);

export const getOpenAICredits = () => get<OpenAICredit[]>(`${PATH}/credits`);

export const addOpenAICredit = (body: OpenAICreditInput) =>
  post<OpenAICredit>(`${PATH}/credits`, body);

export async function updateOpenAICredit(
  id: number,
  body: Partial<OpenAICreditInput>,
): Promise<OpenAICredit> {
  const res = await fetch(`${BASE}${PATH}/credits/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(typeof detail.detail === "string" ? detail.detail : `${res.status}`);
  }
  return res.json();
}

export const deleteOpenAICredit = (id: number) => httpDelete(`${PATH}/credits/${id}`);

// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: Codex runs on a ChatGPT plan — no dollar cost, credits instead.

type Metadata = Record<string, unknown> | null | undefined;

export interface CodexUsage {
  credits: number | null;
  cachedIn: number | null;
  reasoningOut: number | null;
}

function num(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

export function codexUsage(metadata: Metadata): CodexUsage | null {
  if (metadata?.billing !== "chatgpt") return null;
  return {
    credits: num(metadata.codex_credits),
    cachedIn: num(metadata.cached_input_tokens),
    reasoningOut: num(metadata.reasoning_output_tokens),
  };
}

/** Sum of Codex credits, or null when no invocation was billed to a ChatGPT plan. */
export function totalCodexCredits(items: { metadata_: Metadata }[]): number | null {
  const usages = items.map((i) => codexUsage(i.metadata_)).filter((u) => u !== null);
  if (usages.length === 0) return null;
  return usages.reduce((sum, u) => sum + (u.credits ?? 0), 0);
}

export function formatCredits(credits: number): string {
  return credits.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch (D2 measurement): number formats of the Code graph card.
import type { InvocationGraph } from "../../api";

/** The graph block of an agent call's metadata_, if it made graph calls. */
export function graphOf(metadata: Record<string, unknown> | null | undefined): InvocationGraph | null {
  const g = metadata?.graph;
  return g && typeof g === "object" && "calls" in g ? (g as InvocationGraph) : null;
}

/** 1840000 -> "1.84M", 812000 -> "812k", 950 -> "950". */
export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 1 : 2)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}

export function pct(value: number | null | undefined): string {
  return value == null ? "–" : `${value}%`;
}

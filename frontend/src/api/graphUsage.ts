// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch (D2 measurement): Code graph card — graph use of the agents and estimated savings.
import { get } from "./client";
import type { DistributionRange } from "./runDistribution";

export interface GraphSums {
  runs: number;
  calls: number;
  saved_tokens: number;
  saved_usd: number;
  returned_chars: number;
  full_chars: number;
  saved_pct?: number | null;
}

export interface GraphWorker extends GraphSums {
  name: string;
}

/** Per-call figures of the graph calls in range: average tokens (in + out) and turns. */
export interface RunTokens {
  calls: number;
  tokens_per_call: number | null;
  turns_per_call: number | null;
  turn_calls?: number;
  /** Codex calls only: source files printed in the shell (cat, sed -n, ...) instead of graph_read. */
  shell_reads?: number;
  shell_read_calls?: number;
}

export interface GraphUsage {
  range: DistributionRange;
  total_runs: number;
  since: string;
  totals: GraphSums;
  agents: Record<string, number>;
  days: { date: string; saved_tokens: number }[];
  workers: GraphWorker[];
  run_tokens: RunTokens;
}

/** The graph block of one agent call (agent_invocations.metadata_.graph). */
export interface InvocationGraph {
  calls: number;
  tools: Record<string, number>;
  errors: number;
  over_budget: number;
  files: number;
  returned_chars: number;
  full_chars: number;
  saved_tokens: number;
}

export const getGraphUsage = (range: DistributionRange) =>
  get<GraphUsage>(`/bimetri/analytics/graph?range=${range}`);

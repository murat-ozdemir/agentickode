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

export interface GraphUsage {
  range: DistributionRange;
  total_runs: number;
  since: string;
  totals: GraphSums;
  agents: Record<string, number>;
  days: { date: string; saved_tokens: number }[];
  workers: GraphWorker[];
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

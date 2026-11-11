// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: Task Distribution card — runs per server, agent, model, difficulty, type, outcome.
import { get } from "./client";

export type DistributionRange = "7d" | "30d" | "all";
export type DistributionDim = "server" | "agent" | "model" | "difficulty" | "type" | "outcome";

export interface DistributionDay {
  date: string;
  total: number;
  by: Record<DistributionDim, Record<string, number>>;
}

export interface DistributionItem {
  name: string;
  count: number;
  ok_pct?: number | null;
}

export interface RunDistribution {
  range: DistributionRange;
  total: number;
  since: string;
  days: DistributionDay[];
  groups: Record<DistributionDim, DistributionItem[]>;
}

/** One row of the card, used as a Runs list filter. */
export interface DistributionFilter {
  dim: DistributionDim;
  value: string;
  range: DistributionRange;
}

export const getRunDistribution = (range: DistributionRange) =>
  get<RunDistribution>(`/bimetri/analytics/distribution?range=${range}`);

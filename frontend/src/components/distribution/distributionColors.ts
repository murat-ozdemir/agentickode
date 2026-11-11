// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: colors of the Task Distribution card, shared by the history bars and the lists.
import type { DistributionDim } from "../../api";

export const BLUE = "#60a5fa";
export const GRAY = "#4b5563";

const SENTINELS = new Set(["no server", "no agent call", "unknown", "no label"]);
const AGENT: Record<string, string> = { claude: "#f59e0b", codex: "#38bdf8" };
const OUTCOME: Record<string, string> = {
  completed: BLUE,
  failed: "#f97316",
  running: "#a78bfa",
  pending: "#facc15",
};
const CLAUDE_SHADES = ["#f59e0b", "#fbbf24", "#d97706", "#fcd34d"];
const GPT_SHADES = ["#38bdf8", "#7dd3fc", "#0284c7", "#bae6fd"];
const PALETTE = [BLUE, "#34d399", "#f472b6", "#a78bfa", "#facc15", "#2dd4bf", "#fb923c"];

/** Color of one value; `index` is its place in the group, so stacked series stay apart. */
export function seriesColor(dim: DistributionDim, value: string, index: number): string {
  if (SENTINELS.has(value)) return GRAY;
  if (dim === "agent") return AGENT[value] ?? PALETTE[index % PALETTE.length];
  if (dim === "outcome") return OUTCOME[value] ?? GRAY;
  if (dim === "model") {
    const shades = value.startsWith("claude") ? CLAUDE_SHADES : GPT_SHADES;
    return shades[index % shades.length];
  }
  return PALETTE[index % PALETTE.length];
}

/** Bars in the lists are blue except where the color itself means something. */
export function listColor(dim: DistributionDim, value: string, index: number): string {
  if (SENTINELS.has(value)) return GRAY;
  return ["agent", "model", "outcome"].includes(dim) ? seriesColor(dim, value, index) : BLUE;
}

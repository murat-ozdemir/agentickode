// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { GraphUsage } from "../api";

vi.mock("../api", () => ({ getGraphUsage: vi.fn() }));

import CodeGraphCard from "../components/graph/CodeGraphCard";
import { compact } from "../components/graph/graphFormat";
import { getGraphUsage } from "../api";

const sums = (runs: number, calls: number, saved: number, pct: number) => ({
  runs, calls, saved_tokens: saved, saved_usd: 5.1, returned_chars: 21_000, full_chars: 214_000, saved_pct: pct,
});

const DATA: GraphUsage = {
  range: "7d",
  total_runs: 58,
  since: "2026-11-16",
  totals: sums(41, 312, 1_840_000, 91),
  agents: { claude: 30, codex: 11 },
  days: [{ date: "2026-11-22", saved_tokens: 1_840_000 }],
  workers: [
    { name: "worker-1", ...sums(28, 214, 1_250_000, 93) },
    { name: "worker-2", ...sums(13, 98, 590_000, 90) },
  ],
  run_tokens: {
    graph_calls: 20, compared: 12, same_task: 9, same_repo: 3,
    actual_tokens: 9_000_000, baseline_tokens: 15_000_000, saved_pct: 40, turns_per_call: 31.5,
  },
};

describe("CodeGraphCard", () => {
  beforeEach(() => {
    vi.mocked(getGraphUsage).mockReset().mockResolvedValue(DATA);
  });

  it("shows the tiles and the worker table with a total", async () => {
    render(<CodeGraphCard />);
    expect(await screen.findByTestId("graph-summary")).toHaveTextContent("41 of 58 runs");
    const tiles = screen.getByTestId("graph-tiles");
    expect(tiles).toHaveTextContent("41 / 58");
    expect(tiles).toHaveTextContent("71% · claude 30, codex 11");
    expect(tiles).toHaveTextContent("7.6 per run");
    expect(tiles).toHaveTextContent("1.84M");
    expect(tiles).toHaveTextContent("≈ $5.10 at input price");
    expect(tiles).toHaveTextContent("sent 21k of 214k chars");
    expect(tiles).toHaveTextContent("−40%");
    expect(tiles).toHaveTextContent("9.00M vs 15.0M · 12/20 calls · 31.5 turns/call");
    const rows = within(screen.getByTestId("graph-workers")).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      "WorkerRunsCallsSaved%",
      "worker-1282141.25M93%",
      "worker-21398590k90%",
      "Total413121.84M91%",
    ]);
  });

  it("shows a signed increase when graph calls cost more than before", async () => {
    const run_tokens = { ...DATA.run_tokens, saved_pct: -25 };
    vi.mocked(getGraphUsage).mockResolvedValue({ ...DATA, run_tokens });
    render(<CodeGraphCard />);
    expect(await screen.findByTestId("graph-tiles")).toHaveTextContent("+25%");
  });

  it("reloads for another range", async () => {
    render(<CodeGraphCard />);
    await screen.findByTestId("graph-tiles");
    fireEvent.click(screen.getByRole("button", { name: "30d" }));
    await waitFor(() => expect(getGraphUsage).toHaveBeenLastCalledWith("30d"));
    expect(screen.getByRole("button", { name: "30d" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the error", async () => {
    vi.mocked(getGraphUsage).mockReset().mockRejectedValue(new Error("boom"));
    render(<CodeGraphCard />);
    expect(await screen.findByText("Could not load graph usage: boom")).toBeInTheDocument();
  });

  it("formats token counts compactly", () => {
    expect(compact(950)).toBe("950");
    expect(compact(812_000)).toBe("812k");
    expect(compact(1_840_000)).toBe("1.84M");
    expect(compact(12_300_000)).toBe("12.3M");
  });
});

// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, it, expect, vi } from "vitest";

vi.mock("../api", () => ({
  getRuns: vi.fn().mockResolvedValue({
    items: [],
    total: 0,
    offset: 0,
    limit: 50,
  }),
  getStats: vi.fn().mockResolvedValue({
    total_runs: 5, pending: 1, running: 2,
    awaiting_approval: 0, completed: 2, failed: 0,
  }),
  getWorkflowTemplates: vi.fn().mockResolvedValue([]),
  getAnalytics: vi.fn().mockResolvedValue({
    success_rate: 80.0,
    avg_duration_seconds: 120,
    total_runs: 5,
    runs_by_status: { completed: 4, failed: 1 },
    avg_phase_durations: [],
    agent_stats: [],
    runs_over_time: [],
  }),
  getOpenAIUsageSummary: vi.fn().mockResolvedValue({
    enabled: false, month_start: "2026-11-01", month_spend_usd: 0, month_days: [], credits_total_usd: 0,
    first_credit_on: null, spent_since_first_credit_usd: 0, remaining_usd: null,
    last_sync_at: null, sync_error: null, alert: null,
  }),
  getAgentQuotas: vi.fn().mockResolvedValue({ accounts: [], last_sync_at: null, errors: [] }),
  getGraphUsage: vi.fn().mockResolvedValue({
    range: "7d", total_runs: 0, since: "2026-11-16", agents: {}, days: [], workers: [],
    run_tokens: {
      graph_calls: 0, compared: 0, same_task: 0, same_repo: 0,
      actual_tokens: 0, baseline_tokens: 0, saved_pct: null, turns_per_call: null,
    },
    totals: { runs: 0, calls: 0, saved_tokens: 0, saved_usd: 0, returned_chars: 0, full_chars: 0, saved_pct: null },
  }),
  getRunDistribution: vi.fn().mockResolvedValue({
    range: "all", total: 1, since: "2026-11-11",
    days: [{ date: "2026-11-11", total: 1, by: { agent: { codex: 1 } } }],
    groups: {
      server: [], agent: [{ name: "codex", count: 1 }], model: [],
      difficulty: [], type: [], outcome: [],
    },
  }),
}));

vi.mock("../api/client", () => ({
  BASE: "/api",
}));

// Mock EventSource for SSE
class MockEventSource {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onmessage: ((ev: any) => void) | null = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onerror: ((ev: any) => void) | null = null;
  close() {}
}
vi.stubGlobal("EventSource", MockEventSource);

import Dashboard from "../pages/Dashboard";
import { getRuns } from "../api";

const lastRunsQuery = () => vi.mocked(getRuns).mock.lastCall?.[0];

describe("Dashboard", () => {
  it("renders the heading", async () => {
    render(<MemoryRouter><Dashboard /></MemoryRouter>);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("renders the search input", async () => {
    render(<MemoryRouter><Dashboard /></MemoryRouter>);
    expect(screen.getByPlaceholderText("Search runs...")).toBeInTheDocument();
  });

  it("places the subscription limits and Code graph row right above Task Distribution", async () => {
    render(<MemoryRouter><Dashboard /></MemoryRouter>);
    const dist = await screen.findByTestId("task-distribution");
    const row = screen.getByTestId("quota-row");
    expect(dist.previousElementSibling).toBe(row);
    expect(within(row).getByTestId("agent-quota-strip")).toBeInTheDocument();
    expect(within(row).getByTestId("code-graph-card")).toBeInTheDocument();
  });

  it("filters runs by a Task Distribution row and clears it", async () => {
    render(<MemoryRouter><Dashboard /></MemoryRouter>);
    const group = await screen.findByTestId("distribution-group-agent");
    fireEvent.click(within(group).getByText("codex"));
    await waitFor(() =>
      expect(lastRunsQuery()).toMatchObject({ dist_dim: "agent", dist_value: "codex", dist_range: "all" }),
    );
    fireEvent.click(screen.getByTestId("distribution-filter"));
    await waitFor(() => expect(lastRunsQuery()).toMatchObject({ dist_dim: undefined }));
  });

  describe("per page selector", () => {
    beforeEach(() => {
      window.localStorage.clear();
      vi.mocked(getRuns).mockResolvedValue({ items: [], total: 120, offset: 0, limit: 10 });
    });

    it("requests 10 runs per page by default", async () => {
      render(<MemoryRouter><Dashboard /></MemoryRouter>);
      expect(await screen.findByTestId("page-size")).toHaveValue("10");
      expect(lastRunsQuery()).toMatchObject({ limit: 10, offset: 0 });
    });

    it("refetches from the first page and remembers the new size", async () => {
      render(<MemoryRouter><Dashboard /></MemoryRouter>);
      fireEvent.click(await screen.findByText("Next"));
      await waitFor(() => expect(lastRunsQuery()).toMatchObject({ offset: 10 }));
      fireEvent.change(screen.getByTestId("page-size"), { target: { value: "25" } });
      await waitFor(() => expect(lastRunsQuery()).toMatchObject({ limit: 25, offset: 0 }));
      expect(window.localStorage.getItem("dashboard.pageSize")).toBe("25");
    });
  });
});

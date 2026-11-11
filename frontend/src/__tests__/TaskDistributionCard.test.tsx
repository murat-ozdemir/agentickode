// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { RunDistribution } from "../api";

vi.mock("../api", () => ({ getRunDistribution: vi.fn() }));

import TaskDistributionCard from "../components/distribution/TaskDistributionCard";
import { getRunDistribution } from "../api";

const models = ["m1", "m2", "m3", "m4", "m5", "m6", "m7"].map((name, i) => ({ name, count: 7 - i }));

const DATA: RunDistribution = {
  range: "all",
  total: 28,
  since: "2026-10-26",
  days: [{
    date: "2026-10-26",
    total: 28,
    by: { server: {}, agent: { claude: 20, codex: 8 }, model: {}, difficulty: {}, type: {}, outcome: {} },
  }],
  groups: {
    server: [{ name: "agent-1", count: 28, ok_pct: 93 }],
    agent: [{ name: "claude", count: 20 }, { name: "codex", count: 8 }],
    model: models,
    difficulty: [{ name: "easy", count: 28 }, { name: "hard", count: 0 }],
    type: [{ name: "task", count: 20 }, { name: "fix", count: 8 }],
    outcome: [{ name: "completed", count: 28 }],
  },
};

describe("TaskDistributionCard", () => {
  beforeEach(() => {
    vi.mocked(getRunDistribution).mockReset().mockResolvedValue(DATA);
  });

  it("shows the total and every group", async () => {
    render(<TaskDistributionCard onSelect={vi.fn()} />);
    expect(await screen.findByTestId("distribution-total")).toHaveTextContent("28 runs since Oct 26");
    expect(within(screen.getByTestId("distribution-group-server")).getByText("· 93%")).toBeInTheDocument();
    expect(screen.getByText("fix (PR comment)")).toBeInTheDocument();
    expect(getRunDistribution).toHaveBeenCalledWith("all");
  });

  it("shows the top 5 models and expands the rest", async () => {
    render(<TaskDistributionCard onSelect={vi.fn()} />);
    const group = await screen.findByTestId("distribution-group-model");
    expect(within(group).queryByText("m6")).not.toBeInTheDocument();
    fireEvent.click(within(group).getByText("+2 more (3 runs)"));
    expect(within(group).getByText("m7")).toBeInTheDocument();
  });

  it("refetches when the time range changes", async () => {
    render(<TaskDistributionCard onSelect={vi.fn()} />);
    await screen.findByTestId("distribution-total");
    fireEvent.click(screen.getByRole("button", { name: "7d" }));
    await waitFor(() => expect(getRunDistribution).toHaveBeenLastCalledWith("7d"));
  });

  it("switches the Color by dimension without refetching", async () => {
    render(<TaskDistributionCard onSelect={vi.fn()} />);
    await screen.findByTestId("distribution-total");
    const server = screen.getByRole("button", { name: "Server" });
    fireEvent.click(server);
    expect(server).toHaveAttribute("aria-pressed", "true");
    expect(getRunDistribution).toHaveBeenCalledTimes(1);
  });

  it("reports the clicked row with the current range", async () => {
    const onSelect = vi.fn();
    render(<TaskDistributionCard onSelect={onSelect} />);
    const group = await screen.findByTestId("distribution-group-agent");
    fireEvent.click(within(group).getByText("codex"));
    expect(onSelect).toHaveBeenCalledWith({ dim: "agent", value: "codex", range: "all" });
  });

  it("does not offer empty rows as filters", async () => {
    render(<TaskDistributionCard onSelect={vi.fn()} />);
    const group = await screen.findByTestId("distribution-group-difficulty");
    expect(within(group).getByText("hard").closest("button")).toBeDisabled();
  });

  it("shows a friendly error when loading fails", async () => {
    vi.mocked(getRunDistribution).mockRejectedValue(new Error("500"));
    render(<TaskDistributionCard onSelect={vi.fn()} />);
    expect(await screen.findByText(/Could not load the distribution/)).toBeInTheDocument();
  });
});

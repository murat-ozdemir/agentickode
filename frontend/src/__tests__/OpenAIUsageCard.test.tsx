// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  getOpenAIUsageSummary: vi.fn(),
  syncOpenAIUsage: vi.fn(),
  getOpenAICredits: vi.fn().mockResolvedValue([]),
}));

import OpenAIUsageCard from "../components/shared/OpenAIUsageCard";
import { getOpenAIUsageSummary, syncOpenAIUsage, type OpenAIUsageSummary } from "../api";

const summary = (over: Partial<OpenAIUsageSummary> = {}): OpenAIUsageSummary => ({
  enabled: true,
  month_start: "2026-11-01",
  month_spend_usd: 1.3,
  credits_total_usd: 25,
  first_credit_on: "2026-11-01",
  spent_since_first_credit_usd: 1.68,
  remaining_usd: 23.32,
  last_sync_at: "2026-11-10T12:30:00+00:00",
  sync_error: null,
  alert: null,
  ...over,
});

describe("OpenAIUsageCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows spend, credits, remaining and the last update", async () => {
    vi.mocked(getOpenAIUsageSummary).mockResolvedValue(summary());
    render(<OpenAIUsageCard />);
    expect(await screen.findByTestId("openai-month-spend")).toHaveTextContent("$1.30");
    expect(screen.getByTestId("openai-credits")).toHaveTextContent("$25.00");
    expect(screen.getByTestId("openai-remaining")).toHaveTextContent("$23.32");
    expect(screen.getByTestId("openai-last-sync")).toBeInTheDocument();
    expect(screen.queryByTestId("openai-alert")).not.toBeInTheDocument();
  });

  it("turns red with the quota alert and shows a sync error", async () => {
    vi.mocked(getOpenAIUsageSummary).mockResolvedValue(summary({
      alert: { code: "insufficient_quota", source: "mem0", at: "2026-11-10T12:00:00+00:00" },
      sync_error: "OpenAI 401: Invalid admin key",
    }));
    render(<OpenAIUsageCard />);
    expect(await screen.findByTestId("openai-alert")).toHaveTextContent("insufficient_quota");
    expect(screen.getByTestId("openai-usage-card").className).toContain("border-red-500");
    expect(screen.getByTestId("openai-sync-error")).toHaveTextContent("Invalid admin key");
  });

  it("says the admin key is missing and disables refresh", async () => {
    vi.mocked(getOpenAIUsageSummary).mockResolvedValue(summary({ enabled: false, remaining_usd: null }));
    render(<OpenAIUsageCard />);
    expect(await screen.findByTestId("openai-disabled")).toBeInTheDocument();
    expect(screen.getByTestId("openai-sync")).toBeDisabled();
    expect(screen.getByTestId("openai-remaining")).toHaveTextContent("—");
  });

  it("refreshes on demand and opens the credit popup", async () => {
    vi.mocked(getOpenAIUsageSummary).mockResolvedValue(summary());
    vi.mocked(syncOpenAIUsage).mockResolvedValue(summary({ month_spend_usd: 2 }));
    render(<OpenAIUsageCard />);
    fireEvent.click(await screen.findByTestId("openai-sync"));
    await waitFor(() => expect(screen.getByTestId("openai-month-spend")).toHaveTextContent("$2.00"));

    fireEvent.click(screen.getByTestId("openai-add-credit"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});

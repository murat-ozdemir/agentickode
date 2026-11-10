// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ getOpenAICredits: vi.fn().mockResolvedValue([]) }));

import OpenAIBalanceCard from "../components/shared/OpenAIBalanceCard";
import OpenAISpendChart from "../components/shared/OpenAISpendChart";
import type { OpenAIUsageSummary } from "../api";
import type { OpenAIUsage } from "../hooks/useOpenAIUsage";

const summary = (over: Partial<OpenAIUsageSummary> = {}): OpenAIUsageSummary => ({
  enabled: true,
  month_start: "2026-11-01",
  month_spend_usd: 1.3,
  month_days: [
    { day: "2026-11-02", cost_usd: 1 },
    { day: "2026-11-04", cost_usd: 0.3 },
  ],
  credits_total_usd: 25,
  first_credit_on: "2026-11-01",
  spent_since_first_credit_usd: 1.68,
  remaining_usd: 23.32,
  last_sync_at: "2026-11-10T12:30:00+00:00",
  sync_error: null,
  alert: null,
  ...over,
});

const usage = (over: Partial<OpenAIUsageSummary> = {}): OpenAIUsage => ({
  data: summary(over),
  error: null,
  syncing: false,
  reload: vi.fn(),
  refresh: vi.fn(),
});

describe("OpenAIBalanceCard", () => {
  it("shows the remaining credit and the last update", () => {
    render(<OpenAIBalanceCard usage={usage()} />);
    expect(screen.getByTestId("openai-remaining")).toHaveTextContent("$23.32");
    expect(screen.getByTestId("openai-note")).toHaveTextContent("Updated");
    expect(screen.queryByTestId("openai-problem")).not.toBeInTheDocument();
  });

  it("turns red on the quota alert and puts the reason in the tooltip", () => {
    render(<OpenAIBalanceCard usage={usage({
      alert: { code: "insufficient_quota", source: "mem0", at: "2026-11-10T12:00:00+00:00" },
    })} />);
    const card = screen.getByTestId("openai-balance-card");
    expect(card.className).toContain("border-red-500");
    expect(card.title).toContain("insufficient_quota");
    expect(screen.getByTestId("openai-problem")).toBeInTheDocument();
  });

  it("puts the whole sync error in the tooltip", () => {
    render(<OpenAIBalanceCard usage={usage({ sync_error: "OpenAI 403: Missing scopes: api.usage.read" })} />);
    expect(screen.getByTestId("openai-balance-card").title).toBe("OpenAI 403: Missing scopes: api.usage.read");
  });

  it("asks for the billing balance before any credit and disables refresh without the key", () => {
    render(<OpenAIBalanceCard usage={usage({ enabled: false, remaining_usd: null })} />);
    expect(screen.getByTestId("openai-remaining")).toHaveTextContent("—");
    expect(screen.getByTestId("openai-note")).toHaveTextContent("OPENAI_ADMIN_KEY not set");
    expect(screen.getByTestId("openai-sync")).toBeDisabled();
  });

  it("refreshes on demand and opens the credit popup", async () => {
    const u = usage();
    render(<OpenAIBalanceCard usage={u} />);
    fireEvent.click(screen.getByTestId("openai-sync"));
    expect(u.refresh).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("openai-add-credit"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});

describe("OpenAISpendChart", () => {
  it("shows this month's spend", () => {
    render(<OpenAISpendChart data={summary()} />);
    expect(screen.getByTestId("openai-month-spend")).toHaveTextContent("$1.30 this month");
  });

  it("is hidden without the admin key", () => {
    render(<OpenAISpendChart data={summary({ enabled: false })} />);
    expect(screen.queryByTestId("openai-spend-chart")).not.toBeInTheDocument();
  });
});

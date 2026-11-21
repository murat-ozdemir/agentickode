// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentQuotaSummary, QuotaAccount, QuotaWindow } from "../api";

vi.mock("../api", () => ({ getAgentQuotas: vi.fn(), syncAgentQuotas: vi.fn() }));

import { getAgentQuotas, syncAgentQuotas } from "../api";
import AgentQuotaStrip from "../components/shared/AgentQuotaStrip";
import { pacePercent, toneOf, untilText } from "../components/shared/quotaFormat";

const NOW = new Date("2026-11-21T20:00:00Z").getTime();
const inHours = (h: number) => new Date(NOW + h * 3_600_000).toISOString();

const win = (over: Partial<QuotaWindow> = {}): QuotaWindow => ({
  key: "five_hour", label: "5h", minutes: 300, used_percent: 20, resets_at: inHours(4), ...over,
});

const account = (over: Partial<QuotaAccount> = {}): QuotaAccount => ({
  id: 1, provider: "codex", email: "dev@example.com", plan: "plus", org_name: null,
  windows: [win(), win({ key: "weekly", label: "Weekly", minutes: 10080, used_percent: 29, resets_at: inHours(70) })],
  limit_reached: false,
  workers: [{ server_id: 1, server_name: "worker-1", user: "coder" }],
  error: null, observed_at: "2026-11-21T19:55:00Z", checked_at: "2026-11-21T19:55:00Z",
  ...over,
});

const summary = (over: Partial<AgentQuotaSummary> = {}): AgentQuotaSummary => ({
  accounts: [account()], last_sync_at: "2026-11-21T19:55:00Z", errors: [], ...over,
});

beforeEach(() => {
  vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
});
afterEach(() => vi.useRealTimers());

describe("quotaFormat", () => {
  it("measures pace from the time left in the window", () => {
    expect(pacePercent(win({ resets_at: inHours(4) }))).toBeCloseTo(20);
    expect(pacePercent(win({ resets_at: null }))).toBeNull();
  });

  it("colours by limit, threshold and pace", () => {
    expect(toneOf(win({ used_percent: 100 }))).toBe("hit");
    expect(toneOf(win({ used_percent: 75 }))).toBe("warn");
    expect(toneOf(win({ used_percent: 45 }))).toBe("warn"); // 45% used, 20% of the time gone
    expect(toneOf(win({ used_percent: 25 }))).toBe("ok");
  });

  it("formats the countdown", () => {
    expect(untilText(inHours(2.5))).toBe("2h 30m");
    expect(untilText(inHours(50))).toBe("2d 2h");
    expect(untilText(inHours(-1))).toBe("<1m");
  });
});

describe("AgentQuotaStrip", () => {
  it("shows one card per account with plan, e-mail, bars and workers", async () => {
    vi.mocked(getAgentQuotas).mockResolvedValue(summary({
      accounts: [account({
        workers: [
          { server_id: 1, server_name: "worker-1", user: "coder" },
          { server_id: 2, server_name: "worker-2", user: "coder" },
        ],
      })],
    }));
    render(<AgentQuotaStrip />);
    const card = await screen.findByTestId("quota-account");
    expect(within(card).getByText("Codex")).toBeInTheDocument();
    expect(within(card).getByTestId("quota-plan")).toHaveTextContent("plus");
    expect(within(card).getByTestId("quota-email")).toHaveTextContent("dev@example.com");
    expect(within(card).getAllByTestId("quota-worker")).toHaveLength(2);
    expect(within(card).getByTestId("quota-bar-five_hour")).toHaveTextContent("20%");
    expect(within(card).getByTestId("quota-bar-weekly")).toHaveTextContent("29%");
    expect(within(card).getAllByTestId("quota-pace")).toHaveLength(2);
  });

  it("marks an account at its limit with the time until it frees up", async () => {
    vi.mocked(getAgentQuotas).mockResolvedValue(summary({
      accounts: [account({ limit_reached: true, windows: [win({ used_percent: 100, resets_at: inHours(1) })] })],
    }));
    render(<AgentQuotaStrip />);
    expect(await screen.findByTestId("quota-hit")).toHaveTextContent("Limit hit · 1h 00m");
    expect(screen.getByTestId("quota-fill").dataset.tone).toBe("hit");
  });

  it("shows read errors and unreachable workers", async () => {
    vi.mocked(getAgentQuotas).mockResolvedValue(summary({
      accounts: [account({ error: "usage request failed: HTTP 401" })],
      errors: [{ server_name: "worker-3", error: "probe failed: timeout" }],
    }));
    render(<AgentQuotaStrip />);
    expect(await screen.findByTestId("quota-error")).toHaveTextContent("HTTP 401");
    const problems = screen.getByTestId("quota-problems");
    expect(problems).toHaveTextContent("1 issue");
    expect(problems.title).toContain("worker-3");
  });

  it("probes on demand and says when nothing was found", async () => {
    vi.mocked(getAgentQuotas).mockResolvedValue(summary({ accounts: [] }));
    vi.mocked(syncAgentQuotas).mockResolvedValue(summary());
    render(<AgentQuotaStrip />);
    expect(await screen.findByText(/No agent subscriptions found/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Subscription limits" })).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("quota-sync"));
    expect(await screen.findByTestId("quota-account")).toBeInTheDocument();
    expect(syncAgentQuotas).toHaveBeenCalledOnce();
  });
});

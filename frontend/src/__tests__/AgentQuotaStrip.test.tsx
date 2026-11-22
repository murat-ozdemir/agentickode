// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentQuotaSummary, QuotaAccount, QuotaCredits, QuotaWindow } from "../api";

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
  credits: null,
  workers: [{ server_id: 1, server_name: "worker-1", user: "coder" }],
  error: null, observed_at: "2026-11-21T19:55:00Z", checked_at: "2026-11-21T19:55:00Z",
  ...over,
});

const credits = (over: Partial<QuotaCredits> = {}): QuotaCredits => ({
  enabled: true, used: 12.4, limit: 50, balance: 37.6, currency: "USD", used_percent: 24.8,
  limit_reached: false, ...over,
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

  it("shows bought usage credits only when the account has them", async () => {
    vi.mocked(getAgentQuotas).mockResolvedValue(summary({
      accounts: [account({ id: 1 }), account({ id: 2, provider: "claude", credits: credits() })],
    }));
    render(<AgentQuotaStrip />);
    const line = await screen.findByTestId("quota-credits");
    expect(screen.getAllByTestId("quota-credits")).toHaveLength(1);
    expect(screen.getByTestId("quota-credits-amount")).toHaveTextContent("$12.40 / $50.00");
    expect(line.title).toContain("balance $37.60");
    expect(screen.getByTestId("quota-credits-fill").dataset.tone).toBe("ok");
  });

  it("marks an account past its limit but running on credits in amber", async () => {
    vi.mocked(getAgentQuotas).mockResolvedValue(summary({
      accounts: [account({
        provider: "claude", limit_reached: true, credits: credits(),
        windows: [win({ used_percent: 100, resets_at: inHours(2) })],
      })],
    }));
    render(<AgentQuotaStrip />);
    expect(await screen.findByTestId("quota-hit")).toHaveTextContent("On credits · 2h 00m");
  });

  it("goes red when the credit cap is reached too", async () => {
    vi.mocked(getAgentQuotas).mockResolvedValue(summary({
      accounts: [account({
        limit_reached: true, credits: credits({ used: 50, used_percent: 100, limit_reached: true }),
        windows: [win({ used_percent: 100, resets_at: inHours(2) })],
      })],
    }));
    render(<AgentQuotaStrip />);
    expect(await screen.findByTestId("quota-hit")).toHaveTextContent("Limit hit · 2h 00m");
    expect(screen.getByTestId("quota-credits-fill").dataset.tone).toBe("hit");
  });

  it("shows a model-scoped limit as its own bar without counting its reset", async () => {
    vi.mocked(getAgentQuotas).mockResolvedValue(summary({
      accounts: [account({
        limit_reached: true,
        windows: [
          win({ used_percent: 100, resets_at: inHours(3) }),
          win({ key: "scope_fable", label: "Fable", minutes: 10080, used_percent: 100,
            resets_at: inHours(1), scope: "Fable" }),
        ],
      })],
    }));
    render(<AgentQuotaStrip />);
    expect(await screen.findByTestId("quota-bar-scope_fable")).toHaveTextContent("Fable");
    expect(screen.getByTestId("quota-hit")).toHaveTextContent("Limit hit · 3h 00m");
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

describe("AgentQuotaStrip with an aside card", () => {
  const aside = <div data-testid="aside">graph</div>;
  const accounts = (n: number) => Array.from({ length: n }, (_, i) => account({ id: i + 1 }));

  it("puts the aside beside up to 2 accounts and stacks their cards", async () => {
    vi.mocked(getAgentQuotas).mockResolvedValue(summary({ accounts: accounts(2) }));
    render(<AgentQuotaStrip aside={aside} />);
    await screen.findAllByTestId("quota-account");
    expect(screen.getByTestId("quota-row")).toHaveAttribute("data-layout", "side");
    expect(screen.getByTestId("quota-cards").className).toContain("grid-cols-1");
    expect(screen.getByTestId("aside")).toBeInTheDocument();
  });

  it("gives the panel the full width from 3 accounts and moves the aside below", async () => {
    vi.mocked(getAgentQuotas).mockResolvedValue(summary({ accounts: accounts(3) }));
    render(<AgentQuotaStrip aside={aside} />);
    await screen.findAllByTestId("quota-account");
    expect(screen.getByTestId("quota-row")).toHaveAttribute("data-layout", "stacked");
    expect(screen.getByTestId("quota-cards").className).toContain("auto-fit");
  });
});

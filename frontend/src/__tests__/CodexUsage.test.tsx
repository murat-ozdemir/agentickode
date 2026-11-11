// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { AgentInvocation } from "../types";

// vi.mock is hoisted — do not reference variables defined in the test file here
vi.mock("../api", () => ({
  getRunInvocations: vi.fn(),
}));

import { getRunInvocations } from "../api";
import RunCostSummary from "../components/runs/RunCostSummary";
import CodexUsageNote from "../components/runs/CodexUsageNote";
import { codexUsage, totalCodexCredits } from "../utils/codexUsage";

const CODEX_META = {
  model: "gpt-6.1-terra",
  billing: "chatgpt",
  cached_input_tokens: 100000,
  codex_credits: 1.125,
};

function invocation(overrides: Partial<AgentInvocation>): AgentInvocation {
  return {
    id: 1,
    run_id: 42,
    phase_execution_id: null,
    workspace_server_id: null,
    agent_name: "codex",
    phase_name: "implement",
    subtask_index: null,
    subtask_title: null,
    prompt_chars: 100,
    response_chars: 100,
    exit_code: 0,
    files_changed: null,
    duration_seconds: 10,
    status: "success",
    error_message: null,
    started_at: null,
    completed_at: null,
    estimated_tokens_in: 120000,
    estimated_tokens_out: 4000,
    estimated_cost_usd: null,
    session_id: null,
    metadata_: CODEX_META,
    ...overrides,
  };
}

describe("codexUsage", () => {
  it("reads credits and cached tokens from ChatGPT-billed metadata", () => {
    expect(codexUsage(CODEX_META)).toEqual({ credits: 1.125, cachedIn: 100000, reasoningOut: null });
  });

  it("ignores invocations that are not billed to a ChatGPT plan", () => {
    expect(codexUsage({ model: "x", bimetri: true })).toBeNull();
    expect(codexUsage(null)).toBeNull();
    expect(totalCodexCredits([{ metadata_: null }])).toBeNull();
  });

  it("sums credits over Codex invocations only", () => {
    const items = [{ metadata_: CODEX_META }, { metadata_: CODEX_META }, { metadata_: null }];
    expect(totalCodexCredits(items)).toBe(2.25);
  });
});

describe("CodexUsageNote", () => {
  it("renders the plan, credits and cached input", () => {
    render(<CodexUsageNote metadata={CODEX_META} />);
    expect(screen.getByTestId("codex-usage")).toHaveTextContent(
      "ChatGPT plan · 1.13 credits · 100,000 cached in",
    );
  });

  it("says credits are unavailable for an unknown model", () => {
    render(<CodexUsageNote metadata={{ billing: "chatgpt" }} />);
    expect(screen.getByTestId("codex-usage")).toHaveTextContent("credits n/a");
  });
});

describe("RunCostSummary", () => {
  beforeEach(() => {
    (getRunInvocations as ReturnType<typeof vi.fn>).mockResolvedValue([
      invocation({ id: 1, estimated_cost_usd: 0.045 }),
      invocation({ id: 2, agent_name: "claude", estimated_cost_usd: 0.5, metadata_: null }),
    ]);
  });

  it("adds the dollar equivalent of Codex credits to the total", async () => {
    render(<RunCostSummary runId={42} />);
    expect(await screen.findByTestId("codex-credits-total")).toHaveTextContent(
      "incl. 1.13 ChatGPT credits",
    );
    expect(screen.getAllByText("$0.5450").length).toBeGreaterThan(0);
  });
});

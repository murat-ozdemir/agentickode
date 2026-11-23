// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../api", () => ({
  getRunNotebook: vi.fn(),
}));

import { getRunNotebook } from "../api";
import ChainNotebookPanel from "../components/runs/ChainNotebookPanel";

const mocked = vi.mocked(getRunNotebook);

function renderPanel() {
  return render(
    <MemoryRouter>
      <ChainNotebookPanel runId={7} />
    </MemoryRouter>,
  );
}

describe("ChainNotebookPanel", () => {
  beforeEach(() => mocked.mockReset());

  it("lists the entries of the PR's notebook with their kind and run", async () => {
    mocked.mockResolvedValue({
      pr_number: 5,
      entries: [
        { kind: "decision", text: "aufnr boşsa 400", run_id: 7, at: "2026-11-23T10:00:00+00:00" },
        { kind: "ci", text: "kaldı (`abc12345`)", run_id: null, at: "2026-11-23T11:00:00+00:00" },
      ],
    });

    renderPanel();

    expect(await screen.findByText("aufnr boşsa 400")).toBeInTheDocument();
    expect(screen.getByText("Decision")).toBeInTheDocument();
    expect(screen.getByText("CI")).toBeInTheDocument();
    expect(screen.getByText("#7").getAttribute("href")).toBe("/runs/7");
    expect(screen.getByText(/PR #5 · 2 entries/)).toBeInTheDocument();
  });

  it("renders nothing when the notebook is empty", async () => {
    mocked.mockResolvedValue({ pr_number: null, entries: [] });

    renderPanel();

    await Promise.resolve();
    expect(screen.queryByTestId("chain-notebook")).toBeNull();
  });
});

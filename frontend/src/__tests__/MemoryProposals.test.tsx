// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../components/shared/Toast";
import MemoryProposals from "../pages/MemoryProposals";

const proposal = (
  id: number,
  project: string,
  text: string,
  extra: { pr_number?: number | null; source?: string; run_id?: number | null } = {},
) => ({
  id,
  project,
  pr_number: 7,
  source: "merge",
  run_id: null,
  ...extra,
  kind: "lesson",
  text,
  status: "pending",
  mem0_id: null,
  created_at: "2026-11-09T10:00:00Z",
  decided_at: null,
});

const mockGet = vi.fn();
const mockUpdate = vi.fn();
const mockApprove = vi.fn();
const mockReject = vi.fn();

vi.mock("../api", () => ({
  getMemoryProposals: (...args: unknown[]) => mockGet(...args),
  updateMemoryProposal: (...args: unknown[]) => mockUpdate(...args),
  approveMemoryProposal: (...args: unknown[]) => mockApprove(...args),
  rejectMemoryProposal: (...args: unknown[]) => mockReject(...args),
}));

const renderPage = () =>
  render(
    <MemoryRouter>
      <ToastProvider>
        <MemoryProposals />
      </ToastProvider>
    </MemoryRouter>,
  );

describe("MemoryProposals", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue([
      proposal(1, "Org/repo", "Run ruff before push"),
      proposal(2, "Org/other", "Pin the modem firmware"),
    ]);
    mockUpdate.mockResolvedValue({});
    mockApprove.mockResolvedValue({});
    mockReject.mockResolvedValue({});
  });

  it("lists pending proposals and filters by project", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("Run ruff before push")).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith("pending");
    fireEvent.change(screen.getByLabelText("Project"), { target: { value: "Org/other" } });
    expect(screen.queryByTestId("proposal-1")).not.toBeInTheDocument();
    expect(screen.getByTestId("proposal-2")).toBeInTheDocument();
  });

  it("saves edits before approving and removes the card", async () => {
    renderPage();
    const card = await screen.findByTestId("proposal-1");
    fireEvent.change(within(card).getByLabelText("Text"), { target: { value: "Use uv" } });
    fireEvent.change(within(card).getByLabelText("Kind"), { target: { value: "decision" } });
    fireEvent.click(within(card).getByText("Approve"));
    await waitFor(() => expect(mockApprove).toHaveBeenCalledWith(1));
    expect(mockUpdate).toHaveBeenCalledWith(1, { kind: "decision", text: "Use uv" });
    await waitFor(() => expect(screen.queryByTestId("proposal-1")).not.toBeInTheDocument());
  });

  it("approves unchanged proposals without an update call", async () => {
    renderPage();
    const card = await screen.findByTestId("proposal-2");
    fireEvent.click(within(card).getByText("Approve"));
    await waitFor(() => expect(mockApprove).toHaveBeenCalledWith(2));
    expect(mockUpdate).not.toHaveBeenCalled();
  });

  it("rejects and shows errors from the API", async () => {
    mockReject.mockRejectedValueOnce(new Error("Proposal is already approved"));
    renderPage();
    const card = await screen.findByTestId("proposal-1");
    fireEvent.click(within(card).getByText("Reject"));
    expect(await screen.findByText(/Reject failed: Proposal is already approved/)).toBeInTheDocument();
    expect(screen.getByTestId("proposal-1")).toBeInTheDocument();
  });

  it("shows the source and run of agent proposals without a PR", async () => {
    mockGet.mockResolvedValue([
      proposal(3, "Org/repo", "Flyway needs the baseline", {
        pr_number: null,
        source: "agent",
        run_id: 42,
      }),
    ]);
    renderPage();
    const card = await screen.findByTestId("proposal-3");
    expect(within(card).getByText("Agent")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Run #42" })).toHaveAttribute("href", "/runs/42");
    expect(within(card).queryByText(/PR #/)).not.toBeInTheDocument();
    fireEvent.click(within(card).getByText("Approve"));
    expect(await screen.findByText("Saved to project memory")).toBeInTheDocument();
  });

  it("loads another status when its tab is clicked", async () => {
    mockGet.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText("No pending proposals.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("approved"));
    await waitFor(() => expect(mockGet).toHaveBeenLastCalledWith("approved"));
  });
});

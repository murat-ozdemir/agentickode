// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

// bimetri patch: pending memory proposal count on the Memory nav link.
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Nav from "../components/shared/Nav";
import { notifyMemoryProposalsChanged } from "../hooks/useMemoryPendingCount";

const { getMemoryProposals } = vi.hoisted(() => ({ getMemoryProposals: vi.fn() }));
vi.mock("../api/memoryProposals", () => ({ getMemoryProposals }));

const proposals = (n: number) => Array.from({ length: n }, (_, id) => ({ id }));

describe("Memory pending badge", () => {
  beforeEach(() => getMemoryProposals.mockReset());

  it("shows the pending count on the Memory link", async () => {
    getMemoryProposals.mockResolvedValue(proposals(3));
    render(<MemoryRouter><Nav /></MemoryRouter>);
    const badge = await screen.findByTestId("memory-pending-badge");
    expect(badge).toHaveTextContent("3");
    expect(screen.getByText("Memory").closest("a")).toContainElement(badge);
    expect(getMemoryProposals).toHaveBeenCalledWith("pending");
  });

  it("shows nothing while no proposal waits", async () => {
    getMemoryProposals.mockResolvedValue([]);
    render(<MemoryRouter><Nav /></MemoryRouter>);
    await act(async () => {});
    expect(screen.queryByTestId("memory-pending-badge")).not.toBeInTheDocument();
  });

  it("recounts at once when a proposal is decided", async () => {
    getMemoryProposals.mockResolvedValue(proposals(2));
    render(<MemoryRouter><Nav /></MemoryRouter>);
    expect(await screen.findByTestId("memory-pending-badge")).toHaveTextContent("2");
    getMemoryProposals.mockResolvedValue(proposals(1));
    await act(async () => notifyMemoryProposalsChanged());
    expect(screen.getByTestId("memory-pending-badge")).toHaveTextContent("1");
  });

  it("caps a large count at 99+", async () => {
    getMemoryProposals.mockResolvedValue(proposals(120));
    render(<MemoryRouter><Nav /></MemoryRouter>);
    expect(await screen.findByTestId("memory-pending-badge")).toHaveTextContent("99+");
  });
});

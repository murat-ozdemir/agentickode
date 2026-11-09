// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../components/shared/Toast";
import Memory from "../pages/Memory";

const record = (id: string, kind: string, text: string, pr: number | null) => ({
  id,
  text,
  kind,
  source: pr ? "proposal" : "seed",
  pr_number: pr,
  date: pr ? "2026-11-09" : null,
  created_at: "2026-11-01T10:00:00+00:00",
});

const page = (items: ReturnType<typeof record>[], total: number, offset = 0) => ({
  items,
  total,
  offset,
  limit: 50,
  kinds: ["karar", "modul"],
});

const mockRecords = vi.fn();
const mockProjects = vi.fn();
const mockProposals = vi.fn();

vi.mock("../api", () => ({
  getMemoryRecords: (...args: unknown[]) => mockRecords(...args),
  getProjects: () => mockProjects(),
  getMemoryProposals: (...args: unknown[]) => mockProposals(...args),
}));

const renderPage = (url = "/memory?tab=records") =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <ToastProvider>
        <Memory />
      </ToastProvider>
    </MemoryRouter>,
  );

describe("MemoryRecords", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockProjects.mockResolvedValue([
      { repo_owner: "Org", repo_name: "repo" },
      { repo_owner: "Org", repo_name: "other" },
    ]);
    mockRecords.mockImplementation((_project: string, kind: string) => {
      const items = [
        record("a", "karar", "Use ByteFifo.get()", 49),
        record("b", "modul", "Parser module note", null),
      ].filter((r) => !kind || r.kind === kind);
      return Promise.resolve(page(items, items.length));
    });
    mockProposals.mockResolvedValue([]);
  });

  it("loads the first project's records with PR and date", async () => {
    renderPage();
    expect(await screen.findByText("Use ByteFifo.get()")).toBeInTheDocument();
    expect(mockRecords).toHaveBeenCalledWith("Org/other", "", 0, 50);
    expect(screen.getByText("PR #49")).toBeInTheDocument();
    expect(screen.getByText("2 records")).toBeInTheDocument();
  });

  it("filters by kind and reloads on project change", async () => {
    renderPage();
    await screen.findByTestId("record-a");
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "modul" } });
    await waitFor(() => expect(screen.queryByTestId("record-a")).not.toBeInTheDocument());
    expect(mockRecords).toHaveBeenLastCalledWith("Org/other", "modul", 0, 50);
    expect(screen.getByTestId("record-b")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Project"), { target: { value: "Org/repo" } });
    await waitFor(() => expect(mockRecords).toHaveBeenLastCalledWith("Org/repo", "", 0, 50));
    expect(screen.getByLabelText("Kind")).toHaveValue("");
  });

  it("pages through the records", async () => {
    mockRecords.mockImplementation((_p: string, _k: string, offset: number) =>
      Promise.resolve(
        page([record(offset ? "p2" : "p1", "modul", `page at ${offset}`, null)], 120, offset),
      ),
    );
    renderPage();
    expect(await screen.findByText("page at 0")).toBeInTheDocument();
    expect(screen.getByText("120 records")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText("page at 50")).toBeInTheDocument();
    expect(mockRecords).toHaveBeenLastCalledWith("Org/other", "", 50, 50);
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
  });

  it("shows the API error", async () => {
    mockRecords.mockRejectedValueOnce(new Error("mem0 is not configured"));
    renderPage();
    expect(await screen.findByText(/Failed to load records: mem0 is not configured/)).toBeInTheDocument();
  });

  it("switches between the proposals and records tabs", async () => {
    renderPage("/memory");
    expect(await screen.findByText("No pending proposals.")).toBeInTheDocument();
    expect(mockRecords).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("tab", { name: "Records" }));
    expect(await screen.findByText("Use ByteFifo.get()")).toBeInTheDocument();
  });
});

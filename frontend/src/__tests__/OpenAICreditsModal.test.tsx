// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  getOpenAICredits: vi.fn(),
  addOpenAICredit: vi.fn().mockResolvedValue({}),
  updateOpenAICredit: vi.fn().mockResolvedValue({}),
  deleteOpenAICredit: vi.fn().mockResolvedValue(undefined),
}));

import OpenAICreditsModal from "../components/shared/OpenAICreditsModal";
import { addOpenAICredit, deleteOpenAICredit, getOpenAICredits, updateOpenAICredit } from "../api";

const credit = { id: 7, amount_usd: 20, credited_on: "2026-11-01", created_at: null };

function setup() {
  const onChanged = vi.fn();
  render(<OpenAICreditsModal onClose={vi.fn()} onChanged={onChanged} />);
  return onChanged;
}

describe("OpenAICreditsModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getOpenAICredits).mockResolvedValue([credit]);
  });

  it("defaults the date to today and has no note field", async () => {
    setup();
    await screen.findByTestId("credit-7");
    const today = new Date().toISOString().slice(0, 10);
    expect(screen.getByTestId("credit-date")).toHaveValue(today);
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
  });

  it("lists the latest 5 entries and expands to all", async () => {
    const many = Array.from({ length: 7 }, (_, i) => ({ ...credit, id: i + 1 }));
    vi.mocked(getOpenAICredits).mockResolvedValue(many);
    setup();
    await screen.findByTestId("credit-1");
    expect(screen.queryByTestId("credit-6")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("credit-show-all"));
    expect(screen.getByTestId("credit-7")).toBeInTheDocument();
  });

  it("adds a credit and tells the card", async () => {
    const onChanged = setup();
    fireEvent.change(screen.getByTestId("credit-amount"), { target: { value: "10.5" } });
    fireEvent.change(screen.getByTestId("credit-date"), { target: { value: "2026-11-09" } });
    fireEvent.click(screen.getByTestId("credit-save"));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(addOpenAICredit).toHaveBeenCalledWith({ amount_usd: "10.5", credited_on: "2026-11-09" });
  });

  it("edits an existing entry", async () => {
    setup();
    fireEvent.click(await screen.findByTestId("credit-edit-7"));
    expect(screen.getByTestId("credit-amount")).toHaveValue(20);
    fireEvent.change(screen.getByTestId("credit-amount"), { target: { value: "22" } });
    fireEvent.click(screen.getByTestId("credit-save"));
    await waitFor(() =>
      expect(updateOpenAICredit).toHaveBeenCalledWith(7, { amount_usd: "22", credited_on: "2026-11-01" }),
    );
  });

  it("deletes only after the second click", async () => {
    setup();
    fireEvent.click(await screen.findByTestId("credit-delete-7"));
    expect(deleteOpenAICredit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("credit-confirm-7"));
    await waitFor(() => expect(deleteOpenAICredit).toHaveBeenCalledWith(7));
  });

  it("shows a save error", async () => {
    vi.mocked(addOpenAICredit).mockRejectedValueOnce(new Error("POST /x: 422"));
    setup();
    fireEvent.change(screen.getByTestId("credit-amount"), { target: { value: "5" } });
    fireEvent.click(screen.getByTestId("credit-save"));
    expect(await screen.findByTestId("credit-error")).toHaveTextContent("422");
  });
});

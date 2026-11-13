// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ChatMarkdown from "../components/chat/ChatMarkdown";

describe("ChatMarkdown", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders the answer and copies its raw Markdown", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<ChatMarkdown text={"**9** proje\n\n| a | b |\n|---|---|\n| 1 | 2 |"} />);

    expect(screen.getByTestId("chat-markdown").querySelector("strong")?.textContent).toBe("9");
    fireEvent.click(screen.getByTestId("chat-copy"));

    expect(writeText).toHaveBeenCalledWith("**9** proje\n\n| a | b |\n|---|---|\n| 1 | 2 |");
    await waitFor(() => expect(screen.getByTestId("chat-copy")).toHaveAttribute("title", "Copied"));
  });

  it("says so when the clipboard refuses", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<ChatMarkdown text="x" />);

    fireEvent.click(screen.getByTestId("chat-copy"));
    await waitFor(() => expect(screen.getByTestId("chat-copy")).toHaveAttribute("title", "Copy failed"));
  });
});

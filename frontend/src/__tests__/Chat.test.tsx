// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/chat/LocalTerminal", () => ({ default: () => null }));

import Chat from "../pages/Chat";

// jsdom has no layout, so no scrollIntoView.
Element.prototype.scrollIntoView = vi.fn();

const session = (id: string, agent: string, messages: object[] = []) => ({
  session_id: id,
  agent_name: agent,
  display_name: `Chat with ${agent}`,
  status: "active",
  messages,
});

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

describe("Chat", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps a late answer in its own session, not the one open when it arrives", async () => {
    let answer: (r: Response) => void = () => {};
    const store: Record<string, object[]> = { "codex-1": [], "claude-1": [] };
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url === "/api/chat/sessions") {
          return json([session("codex-1", "codex"), session("claude-1", "claude")]);
        }
        if (url === "/api/chat/sessions/codex-1/message" && init?.method === "POST") {
          return new Promise<Response>((resolve) => (answer = resolve));
        }
        const m = url.match(/^\/api\/chat\/sessions\/([\w-]+)$/);
        if (m) return json(session(m[1], m[1].split("-")[0], store[m[1]]));
        return json([]);
      }),
    );

    render(
      <MemoryRouter initialEntries={["/chat/codex-1"]}>
        <Routes>
          <Route path="/chat/:sessionId" element={<Chat />} />
        </Routes>
      </MemoryRouter>,
    );
    const input = await screen.findByPlaceholderText("Ask the agent...");
    await screen.findByText("Chat with codex", { selector: "span" });
    fireEvent.change(input, { target: { value: "soru" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(input).toBeDisabled());

    fireEvent.click(screen.getByText("Chat with claude", { selector: "p" }));
    await screen.findByText("Chat with claude", { selector: "span" });
    expect(screen.getByPlaceholderText("Ask the agent...")).toBeEnabled();
    expect(screen.queryByText("soru")).not.toBeInTheDocument();

    store["codex-1"] = [
      { role: "user", content: "soru" },
      { role: "assistant", content: "codex cevabı" },
    ];
    await act(async () => answer(new Response(JSON.stringify({ response: "codex cevabı" }))));
    expect(screen.queryByText("codex cevabı")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Chat with codex", { selector: "p" }));
    expect(await screen.findByText("codex cevabı")).toBeInTheDocument();
  });
});

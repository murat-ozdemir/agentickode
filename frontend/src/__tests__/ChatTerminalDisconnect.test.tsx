// Copyright (c) 2026 Mechemsi. All rights reserved.
// Licensed under AGPLv3. See LICENSE file.
// Commercial licensing: info@mechemsi.com

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/chat/LocalTerminal", () => ({
  default: ({ onDisconnect }: { onDisconnect?: () => void }) => (
    <button data-testid="drop-socket" onClick={() => onDisconnect?.()} />
  ),
}));

import Chat from "../pages/Chat";

Element.prototype.scrollIntoView = vi.fn();

const terminal = {
  id: 1,
  session_id: "t1",
  agent_name: "codex",
  tmux_name: "lt-codex-t1",
  display_name: "codex session",
  status: "active",
  created_at: "2026-11-13T00:00:00Z",
  last_activity_at: "2026-11-13T00:00:00Z",
};

function stubTerminals(...lists: object[][]) {
  let call = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const body = url === "/api/local-terminals" ? lists[Math.min(call++, lists.length - 1)] : [];
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    }),
  );
}

async function openTerminalAndDropSocket() {
  render(<MemoryRouter><Chat /></MemoryRouter>);
  fireEvent.click(await screen.findByText("codex session"));
  fireEvent.click(await screen.findByTestId("drop-socket"));
}

describe("Chat terminal disconnect", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("says the session ended when the backend no longer has it", async () => {
    stubTerminals([terminal], []);
    await openTerminalAndDropSocket();
    expect(await screen.findByText("This terminal session has ended. Launch a new one."))
      .toBeInTheDocument();
    expect(screen.queryByTestId("drop-socket")).not.toBeInTheDocument();
  });

  it("keeps the terminal open when the session still runs", async () => {
    stubTerminals([terminal], [terminal]);
    await openTerminalAndDropSocket();
    await waitFor(() => {
      const listCalls = vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/local-terminals");
      expect(listCalls).toHaveLength(2);
    });
    expect(screen.getByTestId("drop-socket")).toBeInTheDocument();
    expect(screen.queryByText(/session has ended/)).not.toBeInTheDocument();
  });
});

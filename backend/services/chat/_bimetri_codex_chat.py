# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: the codex chat agent on the current codex CLI.

The upstream command (``codex --quiet -p``) no longer exists. Each message is now one
``codex exec --json`` call:

- New conversation: the chat instructions go in front of the first message (codex exec has
  no system prompt flag), and codex picks the thread id (reported in ``thread.started``); the
  chat stores it as its ``agent_session_id``.
- Later messages: ``codex exec ... resume <thread id> -``.
- Platform tools: codex has no SSE MCP client, so it starts ``_bimetri_codex_mcp_bridge``
  (stdio) which forwards to the platform's ``/mcp/sse``.
- Read-only sandbox: like the Claude chat agent, codex manages the platform through its tools
  and must not change files in the container.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

BRIDGE = str(Path(__file__).with_name("_bimetri_codex_mcp_bridge.py"))
MAX_LOG_LINES = 5


def needs_new_thread(agent_name: str, agent_session_id: str | None, session_id: str) -> bool:
    """A codex chat has no thread yet until codex reported one (it starts as the chat id)."""
    return agent_name == "codex" and agent_session_id in (None, session_id)


def thread_id_from(events: list[dict]) -> str | None:
    """The thread id codex reported in ``thread.started``, if any."""
    for event in events:
        if event.get("type") == "thread.started" and event.get("thread_id"):
            return str(event["thread_id"])
    return None


def codex_message(message: str, system_prompt: str, is_new: bool) -> str:
    if not is_new:
        return message
    return f"{system_prompt}\n\n---\n\nKullanıcının mesajı:\n\n{message}"


def codex_command(msg_path: str, thread_id: str | None, platform_url: str) -> str:
    opts = [
        "--json",
        "--skip-git-repo-check",
        "-s",
        "read-only",
        "-c",
        'approval_policy="never"',
        "-c",
        f"mcp_servers.agentickode.command={json.dumps(sys.executable)}",
        "-c",
        f"mcp_servers.agentickode.args={json.dumps([BRIDGE, f'{platform_url}/mcp/sse'])}",
    ]
    cmd = "codex exec " + " ".join(shlex.quote(o) for o in opts)
    if thread_id:
        cmd += f" resume {shlex.quote(thread_id)}"
    # stderr carries codex's own log lines; they are shown only when no answer came.
    return f"cat {shlex.quote(msg_path)} | {cmd} - 2>&1"


class CodexEvents:
    """Turns ``codex exec --json`` lines into chat text and remembers the thread id."""

    def __init__(self) -> None:
        self.thread_id: str | None = None
        self.events: list[dict] = []
        self._answered = False
        self._log: list[str] = []
        self._errors: set[str] = set()

    def feed(self, line: str) -> list[str]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            self._log = [*self._log, line][-MAX_LOG_LINES:]
            return []
        if not isinstance(event, dict):
            return []
        self.events.append(event)
        etype = event.get("type")
        item = event.get("item") or {}
        if etype == "thread.started":
            self.thread_id = event.get("thread_id")
        elif etype == "item.started" and item.get("type") == "mcp_tool_call":
            return [f"\n[Using tool: {item.get('tool', '')}]\n"]
        elif etype == "item.completed" and item.get("type") == "agent_message":
            self._answered = True
            return [item.get("text", "")]
        elif etype in ("error", "turn.failed"):
            error = event.get("error") or {}
            message = event.get("message") or error.get("message") or line
            if message.startswith("Reconnecting..."):
                return []  # codex retries on its own; only the final error matters
            self._answered = True
            if message in self._errors:
                return []
            self._errors.add(message)
            return [f"\n[Codex hatası: {message}]\n"]
        return []

    def finish(self) -> list[str]:
        if self._answered:
            return []
        if self._log:
            return ["Codex yanıt vermedi:\n" + "\n".join(self._log)]
        return ["Codex yanıt vermedi."]

    def parse(self, stdout: str) -> str:
        parts = [t for line in stdout.splitlines() if line.strip() for t in self.feed(line)]
        return "".join(parts + self.finish()).strip()

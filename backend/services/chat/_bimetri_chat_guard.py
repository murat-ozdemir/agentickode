# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: one agent turn per chat session, and agent processes that really stop.

A chat turn runs ``sh -c "cat msg | codex exec ..."``. Killing only that shell on timeout
left codex running, still holding its thread, so the next message failed with "thread ...
already has an active writer". The agent now runs in its own process group and the whole
group is killed. A second message while a turn is running is refused instead of resuming
the same thread in parallel (and overwriting the first turn's messages).
"""

import asyncio
import contextlib
import os
import signal
from collections.abc import Iterator

# codex and claude chain several MCP calls in one answer; two minutes cut them off. Stay
# under SWAG's 240 s proxy_read_timeout on dev-1, so the page gets the answer, not a 504.
CHAT_TIMEOUT = 230.0
BUSY_DETAIL = "The previous message is still being processed. Wait for its answer."

_busy: set[str] = set()


@contextlib.contextmanager
def session_turn(session_id: str) -> Iterator[bool]:
    """Yield True and hold the session, or yield False when a turn is already running."""
    if session_id in _busy:
        yield False
        return
    _busy.add(session_id)
    try:
        yield True
    finally:
        _busy.discard(session_id)


async def spawn_agent(cmd_str: str, env: dict[str, str]) -> asyncio.subprocess.Process:
    """Start the agent command in its own process group so it can be killed as a whole."""
    return await asyncio.create_subprocess_shell(
        cmd_str,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=True,
    )


def kill_agent(proc: asyncio.subprocess.Process) -> None:
    """Kill the agent's whole process group (the shell, cat and the agent itself)."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)

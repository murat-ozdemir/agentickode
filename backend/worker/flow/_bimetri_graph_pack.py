# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (graf tasarruf planı, Faz 2): the code graph context pack for the prompt.

Before the agent call the worker runs graph_continue on the task in the run's clone and prints
the result with the code of its first entries (scripts/bimetri/_graph_pack.py, at most ~15k
characters). The agent then starts from that code instead of spending its first turns finding
it; each of those turns re-sends the whole context. Any failure, the graph mode being off or no
graph for the clone yet: "" and the agent runs the graph flow itself.
"""

from __future__ import annotations

import base64
import logging
import shlex
from typing import Any

from backend.worker.flow._bimetri_graph_calls import RUN_ENV

logger = logging.getLogger(__name__)

PACK_TIMEOUT_SEC = 60
TASK_CHARS = 6_000  # names and paths for graph_continue; the rest of the text adds nothing
MAX_PACK_CHARS = 20_000  # the worker keeps to 15k; a larger answer is not a pack
_PROGRAM = ".local/share/bimetri-graph/agent_graph.py"


def task_text(title: str | None, description: str | None) -> str:
    return f"{title or ''}\n\n{description or ''}".strip()[:TASK_CHARS]


def pack_command(run_id: int, root: str, task: str, user: str | None) -> str:
    """Shell line that prints the pack; as ``user`` (via runuser) when given."""
    encoded = base64.b64encode(task.encode()).decode()
    program = f"/home/{user}/{_PROGRAM}" if user else f"$HOME/{_PROGRAM}"
    inner = (
        f"test -f {program} || exit 0; echo {encoded} | base64 -d | "
        f"{RUN_ENV}={int(run_id)} python3 {program} pack graphify {shlex.quote(root)}"
    )
    if user:
        return f"runuser -u {shlex.quote(user)} -- bash -c {shlex.quote(inner)}"
    return f"bash -c {shlex.quote(inner)}"


async def context_pack(adapter: Any, run_id: int, root: str | None, task: str) -> str:
    """The prompt section with the pack, or "" (no SSH adapter, no clone, nothing found)."""
    ssh = getattr(adapter, "_ssh", None)
    if ssh is None or not root or not task:
        return ""
    worker = getattr(adapter, "_worker_user", None)
    user = worker if worker and getattr(ssh, "username", "") == "root" else None
    try:
        out, err, rc = await ssh.run_command(
            pack_command(run_id, root, task, user), timeout=PACK_TIMEOUT_SEC
        )
    except Exception:
        logger.warning("context pack of run %s failed", run_id, exc_info=True)
        return ""
    text = (out or "").strip()
    if rc != 0 or not text.startswith("## ") or len(text) > MAX_PACK_CHARS:
        if rc != 0:
            logger.warning("context pack of run %s: rc=%s %s", run_id, rc, (err or "")[-300:])
        return ""
    return "\n\n" + text

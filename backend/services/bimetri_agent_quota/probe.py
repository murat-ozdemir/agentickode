# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: runs ``worker_probe.py`` on one workspace server as the agents' user."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from backend.services.workspace.command_executor import executor_for_server

if TYPE_CHECKING:
    from backend.models import WorkspaceServer

_SCRIPT = (Path(__file__).parent / "worker_probe.py").read_text()
PROBE_TIMEOUT = 60


@dataclass
class ProbeResult:
    user: str
    sections: dict[str, dict] = field(default_factory=dict)
    error: str | None = None


def run_user(server: WorkspaceServer) -> str | None:
    """The user the agents run as, mirroring ``AdapterFactory`` / ``CLIAdapter``.

    None means the connection user itself (no ``runuser`` wrap).
    """
    wu = server.worker_user
    if getattr(server, "server_type", "remote") == "local":
        return wu if (wu and wu != "root") else None
    if wu and server.worker_user_status == "ready" and server.username == "root":
        return wu
    return None


async def probe_server(server: WorkspaceServer) -> ProbeResult:
    user = run_user(server)
    executor = executor_for_server(server)
    display_user = user or getattr(executor, "username", None) or server.username
    cmd = "python3 -"
    if user:
        cmd = f"runuser -l {shlex.quote(user)} -c {shlex.quote(cmd)}"
    try:
        stdout, stderr, rc = await executor.run_command(cmd, timeout=PROBE_TIMEOUT, input=_SCRIPT)
    except Exception as e:  # unreachable server, auth failure, timeout
        return ProbeResult(display_user, error=f"probe failed: {e}"[:300])
    if rc != 0:
        detail = stderr.strip()[-200:] or f"exit code {rc}"
        return ProbeResult(display_user, error=f"probe failed: {detail}")
    try:
        sections = json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return ProbeResult(display_user, error="probe printed no JSON")
    if not isinstance(sections, dict):
        return ProbeResult(display_user, error="probe printed no JSON object")
    return ProbeResult(
        display_user, sections={k: v for k, v in sections.items() if isinstance(v, dict)}
    )

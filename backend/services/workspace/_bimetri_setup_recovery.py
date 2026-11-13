# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: fail server setups that a backend restart interrupted.

Server setup runs as an asyncio task inside the backend process. A restart kills it, but the
row keeps ``status="setting_up"`` with a ``running`` step, so the servers page shows the setup
as in progress forever. At startup no setup task can be alive yet, so any such row is marked
``setup_failed`` and its running steps ``failed``; the page then offers to retry.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import WorkspaceServer

logger = logging.getLogger("agentickode.server_setup")

INTERRUPTED = "Interrupted by a backend restart"


async def fail_interrupted_setups(db: AsyncSession) -> list[str]:
    """Mark setups left ``setting_up`` by a previous process as failed; returns server names."""
    servers = (
        (await db.execute(select(WorkspaceServer).where(WorkspaceServer.status == "setting_up")))
        .scalars()
        .all()
    )
    now = datetime.now(UTC).isoformat()
    for server in servers:
        log = dict(server.setup_log or {})  # type: ignore[arg-type]
        for step, entry in log.items():
            if entry.get("status") == "running":
                log[step] = {"status": "failed", "error": INTERRUPTED, "timestamp": now}
        server.setup_log = log  # type: ignore[assignment]
        server.status = "setup_failed"  # type: ignore[assignment]
        server.error_message = INTERRUPTED  # type: ignore[assignment]
        logger.warning("Setup of server %s was interrupted by a restart", server.name)
    await db.commit()
    return [str(s.name) for s in servers]

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: respect a cancel that arrives while the agent is still working.

The cancel endpoint only writes ``status='cancelled'`` in its own session. The executor's
``run`` object is stale (``expire_on_commit=False``), so without this check a finishing run
posted its result and overwrote the cancel with ``completed`` / ``failed``.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskRun

logger = logging.getLogger("agentickode.flow.cancel")


async def was_cancelled(run: TaskRun, session: AsyncSession) -> bool:
    """True (and ``run.status`` set to cancelled) when the stored run was cancelled meanwhile.

    Never raises: a broken session counts as not cancelled so the caller's own
    error handling still runs.
    """
    try:
        with session.no_autoflush:
            result = await session.execute(select(TaskRun.status).where(TaskRun.id == run.id))
        stored = result.scalar_one_or_none()
    except Exception:
        logger.warning("Run #%s: cancel check failed", run.id, exc_info=True)
        return False
    if stored != "cancelled":
        return False
    run.status = "cancelled"
    return True

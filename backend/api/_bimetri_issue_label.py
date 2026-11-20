# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: start a run when ``ai-task`` is added to an issue that is already open.

Gitea sends issue label changes as the ``issue_label`` hook event with action
``label_updated``; the payload carries the issue's labels after the change. The
platform changes status/* labels on the issue while it works, so each of those
events also shows ``ai-task``: an issue that already has a run is skipped. One
lock makes the check and the insert atomic, because Gitea sends both ``opened``
and ``label_updated`` when an issue is created with its labels.

The queued issue gets ``status/open`` and the bot as assignee before its run is
saved: the worker picks a run up as soon as it is committed and sets
``status/in-progress``, and status labels are exclusive, so a later ``open``
would wipe it.
"""

import asyncio
import logging
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ProjectConfig, TaskRun

logger = logging.getLogger("agentickode.webhooks")

ISSUE_ACTIONS = ("opened", "labeled", "label_updated")

# The backend runs as a single uvicorn process, so a process-wide lock is enough.
issue_run_lock = asyncio.Lock()


def trigger_action(action: str) -> str:
    """Map Gitea's ``label_updated`` to the trigger vocabulary (``labeled``)."""
    return "labeled" if action == "label_updated" else action


async def issue_has_run(db: AsyncSession, project_id: str, task_id: str) -> bool:
    """True when any run (queued, running or finished) exists for this issue."""
    q = (
        select(TaskRun.id)
        .where(TaskRun.project_id == project_id, TaskRun.task_id == task_id)
        .limit(1)
    )
    return (await db.execute(q)).first() is not None


async def mark_issue_queued(
    db: AsyncSession, project: ProjectConfig, repo_full_name: str, number: int
) -> None:
    """Put status/open on the issue and assign the bot; a failure only logs."""
    from backend.services.git import get_git_provider
    from backend.services.http_client import get_http_client
    from backend.worker.phases._helpers import get_project_token

    try:
        token = await get_project_token(
            SimpleNamespace(
                git_provider="gitea",
                project_id=project.project_id,
                workspace_server_id=getattr(project, "workspace_server_id", None),
            ),
            db,
        )
        provider = get_git_provider("gitea", get_http_client(), access_token=token)
        await provider.set_status_label(repo_full_name, number, "status/open")
        await provider.assign_self(repo_full_name, number)
    except Exception:
        logger.warning("Issue #%s status/open ya da atama yapilamadi", number, exc_info=True)

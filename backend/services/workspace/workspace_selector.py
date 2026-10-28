# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""Workspace server selection strategy for multi-workspace projects.

Selects the least-loaded workspace server assigned to a project.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ProjectWorkspaceServer, TaskRun


async def select_workspace_for_run(
    project_id: str,
    session: AsyncSession,
    *,
    exclude_server_ids: list[int] | None = None,
) -> int | None:
    """Return workspace_server_id with fewest active runs for the project.

    Picks from project's assigned workspace servers ordered by:
    1. Number of active (pending/running) runs ascending
    2. Priority ascending (lower = higher priority)

    Returns None if the project has no assigned workspace servers or
    all servers are excluded.
    """
    exclude = set(exclude_server_ids or [])

    # bimetri yamasi: aktif kosu sayisi tum projelerde (makine paylasiliyor); esitse en uzun suredir
    # kosu almayan sunucu, sonra oncelik. Boylece sirali kosular da makineler arasinda doner.
    active_counts = (
        select(
            TaskRun.workspace_server_id,
            func.count(TaskRun.id).label("active"),
        )
        .where(
            TaskRun.status.in_(["pending", "running"]),
            TaskRun.workspace_server_id.is_not(None),
        )
        .group_by(TaskRun.workspace_server_id)
        .subquery()
    )
    last_used = (
        select(
            TaskRun.workspace_server_id,
            func.max(TaskRun.id).label("last_run"),
        )
        .where(TaskRun.workspace_server_id.is_not(None))
        .group_by(TaskRun.workspace_server_id)
        .subquery()
    )

    stmt = (
        select(ProjectWorkspaceServer.workspace_server_id)
        .outerjoin(
            active_counts,
            ProjectWorkspaceServer.workspace_server_id == active_counts.c.workspace_server_id,
        )
        .outerjoin(
            last_used,
            ProjectWorkspaceServer.workspace_server_id == last_used.c.workspace_server_id,
        )
        .where(ProjectWorkspaceServer.project_id == project_id)
        .order_by(
            func.coalesce(active_counts.c.active, 0).asc(),
            func.coalesce(last_used.c.last_run, 0).asc(),
            ProjectWorkspaceServer.priority.asc(),
        )
        .limit(1)
    )
    if exclude:
        stmt = stmt.where(ProjectWorkspaceServer.workspace_server_id.not_in(exclude))

    result = await session.execute(stmt)
    return result.scalar_one_or_none()

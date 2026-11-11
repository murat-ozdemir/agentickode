# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: reads the rows behind the Task Distribution card."""

from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AgentInvocation, TaskRun, WorkspaceServer
from backend.services.bimetri_run_distribution import RunRow


class RunDistributionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_rows(self, since: date | None) -> list[RunRow]:
        q = select(
            TaskRun.id,
            TaskRun.created_at,
            TaskRun.status,
            TaskRun.task_source_meta,
            WorkspaceServer.name,
        ).outerjoin(WorkspaceServer, WorkspaceServer.id == TaskRun.workspace_server_id)
        if since is not None:
            q = q.where(TaskRun.created_at >= datetime.combine(since, time.min))
        rows = {
            run_id: RunRow(run_id, created, status, meta or {}, server)
            for run_id, created, status, meta, server in (await self._session.execute(q)).all()
        }
        if not rows:
            return []

        calls = await self._session.execute(
            select(AgentInvocation.run_id, AgentInvocation.agent_name, AgentInvocation.metadata_)
            .where(AgentInvocation.run_id.in_(rows))
            .order_by(AgentInvocation.run_id, AgentInvocation.id)
        )
        for run_id, agent, meta in calls.all():
            rows[run_id].calls.append((agent, (meta or {}).get("model")))
        return list(rows.values())

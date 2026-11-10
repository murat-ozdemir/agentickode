# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 2): refresh the agents' code graph on the workers after a merge.

The graph MCP (agent_graph.py serve) updates the graph when the clone's HEAD has moved; after a
merge that costs the next run about 50 s. The merge webhook calls schedule_refresh instead: on
each worker of the project with no pending or running run of it, the clone is synced to
origin/<default branch> and the graph updated, in the background. Both happen under flock on
<clone>/.git/bimetri-graph.lock, which workspace_setup waits for before it syncs the clone.
Workers without agent_graph.py (agent-graph-mcp.sh install) are skipped.
"""

from __future__ import annotations

import asyncio
import logging
import shlex

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ProjectConfig, ProjectWorkspaceServer, TaskRun, WorkspaceServer
from backend.services.run_factory import resolve_workspace_path
from backend.services.workspace.command_executor import CommandExecutor, executor_for_server

logger = logging.getLogger("agentickode.bimetri_graph")

GRAPH = "~/.local/share/bimetri-graph/agent_graph.py"  # the worker user's, expanded by its shell
LOCK = ".git/bimetri-graph.lock"
REFRESH_TIMEOUT = 900  # first build of a large repo; an incremental update takes seconds
WAIT_TIMEOUT = 600
_tasks: set[asyncio.Task] = set()


def clone_path(project: ProjectConfig, server: WorkspaceServer) -> str:
    """The clone workspace_setup uses for project on server."""
    path = resolve_workspace_path(project, "")
    if path.startswith("/"):
        return path
    return f"{server.workspace_root or '/home/workspace'}/{path}".rstrip("/")


def refresh_command(workspace: str, branch: str, user: str | None) -> str:
    """Shell line, run as the SSH user: sync the idle clone, then update the graph as user.

    flock -n: a refresh already running for this clone wins; exit 1 means skipped.
    """
    ws, br = shlex.quote(workspace), shlex.quote(branch)

    def as_user(cmd: str) -> str:
        return f"runuser -l {shlex.quote(user)} -c {shlex.quote(cmd)}" if user else cmd

    sync = (
        f"git fetch -q origin && git checkout -q -f {br} && git reset -q --hard origin/{br} "
        "&& git clean -qfd"
    )
    if user:  # git ran as root: give the clone back, as workspace_setup does
        sync += f" && chown -R {shlex.quote(user)}:{shlex.quote(user)} ."
    update = as_user(f"/usr/bin/python3 {GRAPH} update graphify {ws}")
    return (
        f"cd {ws} && test -d .git && {as_user(f'test -f {GRAPH}')} "
        f"&& flock -n {LOCK} sh -c {shlex.quote(f'{sync} && {update}')}"
    )


async def wait_for_refresh(ssh: CommandExecutor, workspace: str) -> None:
    """workspace_setup: let a merge refresh of this clone finish before the run syncs it."""
    ws = shlex.quote(workspace)
    cmd = f"cd {ws} 2>/dev/null && test -f {LOCK} && flock -w {WAIT_TIMEOUT} {LOCK} true"
    try:
        await ssh.run_command(cmd, timeout=WAIT_TIMEOUT + 10)
    except Exception:
        logger.warning("graph refresh lock wait failed for %s", workspace, exc_info=True)


async def refresh(ssh: CommandExecutor, name: str, workspace: str, branch: str, user) -> None:
    try:
        out, err, code = await ssh.run_command(
            refresh_command(workspace, branch, user), timeout=REFRESH_TIMEOUT
        )
    except Exception:
        logger.warning("graph refresh on %s failed", name, exc_info=True)
        return
    tail = (out.strip() or err.strip()).splitlines()[-1:] or [""]
    logger.info("graph refresh on %s %s: exit %s %s", name, workspace, code, tail[0])


async def schedule_refresh(db: AsyncSession, project: ProjectConfig) -> list[str]:
    """Start a background refresh on each idle worker of project; returns their names."""
    ws_type = (project.workspace_config or {}).get("workspace_type", "existing")
    if ws_type != "existing" or project.local_path:
        return []  # a scaffold or the operator's own checkout: nothing of ours to sync
    busy = select(TaskRun.workspace_server_id).where(
        TaskRun.project_id == project.project_id,
        TaskRun.status.in_(["pending", "running"]),
        TaskRun.workspace_server_id.is_not(None),
    )
    linked = select(ProjectWorkspaceServer.workspace_server_id).where(
        ProjectWorkspaceServer.project_id == project.project_id
    )
    rows = await db.execute(
        select(WorkspaceServer).where(
            WorkspaceServer.id.in_(linked), WorkspaceServer.id.not_in(busy)
        )
    )
    started = []
    for server in rows.scalars().all():
        user = project.worker_user_override or server.worker_user
        user = user if user and user != server.username else None
        job = refresh(
            executor_for_server(server),
            server.name,
            clone_path(project, server),
            project.default_branch,
            user,
        )
        task = asyncio.create_task(job)
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        started.append(server.name)
    return started

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: what a run's start/finish/failure event carries for notifications.

The Slack message names the run type, the issue and PR, the server and the result,
so the payload gathers them here instead of only the project id and title.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskRun, WorkspaceServer
from backend.services.bimetri_run_distribution import run_type


def review_outcome(summary: str) -> str | None:
    """The verdict the review agent ends its comment with, if any."""
    tail = summary[-400:]
    if "Birleştirilebilir" in tail:
        return "Birleştirilebilir"
    if "Değişiklik gerekli" in tail:
        return "Değişiklik gerekli"
    return None


def _outcome(kind: str, run: TaskRun) -> str | None:
    if kind == "test":
        return (run.coding_results or {}).get("test_outcome")
    if kind == "review":
        return review_outcome(str((run.review_result or {}).get("summary") or ""))
    return None


def _duration_seconds(run: TaskRun) -> float | None:
    if not (run.started_at and run.completed_at):
        return None
    try:
        return (run.completed_at - run.started_at).total_seconds()
    except TypeError:  # naive vs aware timestamps
        return None


async def run_event_payload(run: TaskRun, session: AsyncSession) -> dict[str, Any]:
    meta = run.task_source_meta or {}
    results = run.coding_results or {}
    kind = run_type(meta)
    server = None
    if run.workspace_server_id:
        try:  # a lookup failure must not stop the failure path that follows the event
            server = await session.scalar(
                select(WorkspaceServer.name).where(WorkspaceServer.id == run.workspace_server_id)
            )
        except Exception:
            server = None
    return {
        "run_id": run.id,
        "title": run.title,
        "project_id": run.project_id,
        "run_kind": kind,
        "repo": run.repo_name,
        "issue_number": meta.get("issue_number"),
        "pr_number": meta.get("pr_number"),
        "pr_title": meta.get("pr_title"),
        "pr_url": run.pr_url or meta.get("pr_url"),
        "server": server,
        "agent": results.get("agent"),
        "model": results.get("model"),
        "outcome": _outcome(kind, run),
        "duration_seconds": _duration_seconds(run),
    }

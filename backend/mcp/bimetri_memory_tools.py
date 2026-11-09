# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: project-memory tools for agents, served by the memory-mcp service.

Agents read the mem0 records of a project registered in AgenticKode and queue proposals for
human review on the Memory page. Nothing here writes to mem0 directly.
"""

from typing import Literal

from fastmcp.exceptions import ToolError

from backend.api.bimetri_memories import to_record
from backend.database import async_session
from backend.models import MemoryProposal, TaskRun
from backend.repositories.memory_proposal_repo import MemoryProposalRepository
from backend.repositories.project_config_repo import ProjectConfigRepository
from backend.services.bimetri_mem0 import (
    HISTORY_KINDS,
    KNOWLEDGE_KINDS,
    list_memories,
    mem0_enabled,
    search_memories,
)

MAX_LIMIT = 20
MAX_PROPOSALS_PER_RUN = 3
MAX_TEXT = 2000
_SCOPE_KINDS = {"knowledge": KNOWLEDGE_KINDS, "history": HISTORY_KINDS, "all": ()}


async def _registered(project: str) -> None:
    owner, _, name = project.partition("/")
    if not owner or not name or "/" in name:
        raise ToolError("project must be '<owner>/<repo>'")
    async with async_session() as session:
        if await ProjectConfigRepository(session).find_by_repo(owner, name) is None:
            raise ToolError(f"{project} is not a project registered in AgenticKode")


async def _readable(project: str) -> None:
    if not mem0_enabled():
        raise ToolError("project memory (mem0) is not configured")
    await _registered(project)


def _records(rows: list[dict], with_score: bool = False) -> list[dict]:
    out = []
    for raw in rows:
        record = to_record(raw).model_dump(exclude_none=True, exclude={"id"})
        if with_score and isinstance(raw.get("score"), int | float):
            record["score"] = round(raw["score"], 3)
        out.append(record)
    return out


async def search_project_memory(
    project: str,
    query: str,
    scope: Literal["knowledge", "history", "all"] = "knowledge",
    limit: int = 8,
) -> list[dict]:
    """Search a project's memory for the records closest to a query.

    Args:
        project: "<owner>/<repo>" of the repository you are working on.
        query: What you are looking for, in a sentence (a module, decision, error...).
        scope: "knowledge" = project, module, decision, lesson, pitfall, how-to records;
            "history" = what earlier PRs did; "all" = both.
        limit: Maximum records to return (1-20).

    Returns:
        Records with kind, text, source, pr_number, date and similarity score.
        The code wins when a record contradicts it.
    """
    await _readable(project)
    try:
        rows = await search_memories(
            project, query.strip()[:1000], _SCOPE_KINDS[scope], max(1, min(limit, MAX_LIMIT))
        )
    except Exception as e:
        raise ToolError(f"mem0 search failed: {e}") from e
    return _records(rows, with_score=True)


async def list_project_memory(
    project: str, kind: str | None = None, limit: int = MAX_LIMIT
) -> list[dict]:
    """List a project's memory records, newest first.

    Args:
        project: "<owner>/<repo>" of the repository you are working on.
        kind: Only this kind: proje, modul, karar, ders, tuzak, calisma, ozellik_gecmisi.
        limit: Maximum records to return (1-20).
    """
    if kind is not None and kind not in KNOWLEDGE_KINDS + HISTORY_KINDS:
        raise ToolError(f"unknown kind {kind!r}")
    await _readable(project)
    try:
        rows = await list_memories(project)
    except Exception as e:
        raise ToolError(f"mem0 read failed: {e}") from e
    if kind:
        rows = [r for r in rows if (r.get("metadata") or {}).get("tur") == kind]
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return _records(rows[: max(1, min(limit, MAX_LIMIT))])


async def propose_memory(
    project: str,
    kind: Literal["lesson", "pitfall", "decision"],
    text: str,
    run_id: int | None = None,
    pr_number: int | None = None,
) -> dict:
    """Propose a record for the project memory; a human approves or rejects it.

    Only propose what a later task cannot learn from the code: a decision and its reason,
    a pitfall that cost time, a lesson. No task summaries, no secrets.

    Args:
        project: "<owner>/<repo>" of the repository you are working on.
        kind: "decision", "pitfall" or "lesson".
        text: One or two self-contained sentences.
        run_id: The AgenticKode run id given in your prompt.
        pr_number: Your PR number, if it already exists.
    """
    text = " ".join(text.split())
    if not text or len(text) > MAX_TEXT:
        raise ToolError(f"text must be 1-{MAX_TEXT} characters")
    await _registered(project)
    async with async_session() as session:
        repo = MemoryProposalRepository(session)
        if run_id is not None:
            run = await session.get(TaskRun, run_id)
            if run is None or f"{run.repo_owner}/{run.repo_name}" != project:
                raise ToolError(f"run {run_id} does not belong to {project}")
            if await repo.count_for_run(run_id) >= MAX_PROPOSALS_PER_RUN:
                raise ToolError(f"at most {MAX_PROPOSALS_PER_RUN} proposals per run")
        if text in await repo.pending_texts(project):
            return {"status": "duplicate", "message": "The same proposal is already pending."}
        row = MemoryProposal(
            project=project,
            kind=kind,
            text=text,
            source="agent",
            run_id=run_id,
            pr_number=pr_number,
        )
        await repo.add_all([row])
        await session.commit()
        return {"status": "pending", "id": row.id, "message": "Waiting for human review."}

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 7): what goes into a PR's chain notebook, and the prompt.

A finished or failed run adds its decisions, its open question and a run record; the webhooks
add CI results and the human's `devam` answers. Gitea only; a failure never breaks the caller.
"""

import contextlib
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskRun
from backend.worker.phases._bimetri_notebook import (
    add_entries,
    entry,
    load,
    notebook_block,
    render,
    split_block,
)
from backend.worker.phases._bimetri_soru import acik_soru, ajan_raporu

logger = logging.getLogger("agentickode.phases.bimetri_notebook")

QUESTION_CHARS = 800
_RESULT_RX = re.compile(r"\*\*Sonuç:\*\*\s*(.+)")


def run_pr_number(run: TaskRun) -> int | None:
    """The PR of the run's chain: the PR the run works on, or the PR it opened."""
    if run.git_provider != "gitea":
        return None
    meta = run.task_source_meta or {}
    m = re.search(r"/pulls/(\d+)", run.pr_url or meta.get("pr_url") or "")
    n = meta.get("pr_number") or (m.group(1) if m else None)
    return int(n) if n else None


def _label(run: TaskRun) -> str:
    mode = (run.task_source_meta or {}).get("review_mode")
    if mode == "test":
        return "Test"
    if mode == "fix":
        return "Düzeltme"
    if run.review_result or mode:
        return "İnceleme"
    return "Kod"


def _report(run: TaskRun) -> str:
    if run.review_result and isinstance(run.review_result.get("summary"), str):
        return run.review_result["summary"]
    return ajan_raporu(run)


def _outcome(run: TaskRun, report: str) -> str:
    test = (run.coding_results or {}).get("test_outcome")
    if test:
        return test
    if run.status == "failed":
        return "durdu: " + (run.error_message or "")[:200]
    m = _RESULT_RX.search(report)
    return m.group(1).strip() if m else "tamamlandı"


def run_entries(run: TaskRun) -> list[dict]:
    """Decisions, the open question and the run record of a finished or failed run."""
    report = _report(run)
    decisions, rest = split_block(notebook_block(report) or "")
    new = [entry("decision", d, run.id) for d in decisions]
    question = acik_soru(report)
    if question:
        new.append(entry("question", question[:QUESTION_CHARS], run.id))
    text = f"{_label(run)}: {_outcome(run, report)}"
    new.append(entry("run", f"{text}\n{rest}" if rest else text, run.id))
    return new


async def _add(session: AsyncSession, project_id: str, pr_number: int, new) -> None:
    try:
        await add_entries(session, project_id, pr_number, new)
    except Exception:
        logger.warning("Notebook of PR #%s not written", pr_number, exc_info=True)
        with contextlib.suppress(Exception):
            await session.rollback()


async def record_run(session: AsyncSession, run: TaskRun) -> None:
    n = run_pr_number(run)
    if n is not None:
        await _add(session, run.project_id, n, run_entries(run))


async def record_answer(
    session: AsyncSession, project_id: str, pr_number: int, login: str, answer: str
) -> None:
    """The human's `devam <yanıt>`: a permanent entry every later agent follows."""
    await _add(session, project_id, pr_number, [entry("answer", f"{login}: {answer}")])


async def record_ci(
    session: AsyncSession, project_id: str, pr_number: int, sha: str, passed: bool
) -> None:
    text = f"{'geçti' if passed else 'kaldı'} (`{sha[:8]}`)"
    await _add(session, project_id, pr_number, [entry("ci", text)])


async def notebook_prompt(session: AsyncSession, run: TaskRun) -> str:
    """The notebook rules, and the PR's notebook when it has entries."""
    from backend.worker.flow._bimetri_agent_rules import NOTEBOOK_RULES

    n = run_pr_number(run)
    if n is None:
        return NOTEBOOK_RULES
    try:
        row = await load(session, run.project_id, n)
    except Exception:
        logger.warning("Notebook not read for run %s", run.id, exc_info=True)
        return NOTEBOOK_RULES
    if row is None or not row.entries:
        return NOTEBOOK_RULES
    return (
        NOTEBOOK_RULES + f"\n## Zincir defteri (PR #{n}; eskiden yeniye)\n\n" + render(row.entries)
    )

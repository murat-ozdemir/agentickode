# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 7): the chain notebook of a PR, kept in the DB.

Each agent ends its last message with a short `### Defter` block: decisions, open points,
changed files. The platform adds each run's outcome, CI results, the questions the loop stopped
on and the human's `devam` answers. The notebook goes into every prompt of the PR's chain in place
of the PR's comment history. Decisions, questions and answers are never dropped or clipped; of the
run and CI records only the last few stay, within ~8k characters in total.
"""

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ChainNotebook

MAX_CHARS = 8000
MAX_RECORDS = 5  # run and CI records
RECORD_CHARS = 1500
PERMANENT = ("decision", "question", "answer")
LABELS = {"decision": "Karar", "question": "Soru", "answer": "Yanıt", "run": "Koşu", "ci": "CI"}

_HEADING_RX = re.compile(r"(?im)^#{2,4}\s*defter\s*:?\s*$")
_END_RX = re.compile(r"(?m)^(?:#{1,4}\s|\*\*Sonuç:\*\*|---\s*$)")
_DECISION_RX = re.compile(r"(?i)^[-*]\s*(?:\*\*)?karar(?:lar)?(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.+)$")


def notebook_block(report: str) -> str | None:
    """Text under the agent's `### Defter` heading; None when there is none."""
    m = _HEADING_RX.search(report or "")
    if not m:
        return None
    body = report[m.end() :]
    end = _END_RX.search(body)
    block = (body[: end.start()] if end else body).strip()
    return block or None


def split_block(block: str) -> tuple[list[str], str]:
    """(decision lines, the rest of the block as the run record's detail)."""
    decisions, rest = [], []
    for line in (block or "").splitlines():
        s = line.strip()
        if not s:
            continue
        m = _DECISION_RX.match(s)
        if m:
            decisions.append(m.group(1).strip())
        else:
            rest.append(s)
    return decisions, "\n".join(rest)[:RECORD_CHARS]


def entry(kind: str, text: str, run_id: int | None = None) -> dict:
    return {
        "kind": kind,
        "text": text.strip(),
        "run_id": run_id,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _size(entries: list[dict]) -> int:
    return sum(len(e.get("text") or "") + 20 for e in entries)


def prune(entries: list[dict]) -> list[dict]:
    """All decisions, questions and answers; the last MAX_RECORDS records, oldest dropped first
    while the notebook is over MAX_CHARS."""
    records = [i for i, e in enumerate(entries) if e.get("kind") not in PERMANENT]
    keep = set(records[-MAX_RECORDS:])
    out = [e for i, e in enumerate(entries) if e.get("kind") in PERMANENT or i in keep]
    while _size(out) > MAX_CHARS:
        i = next((i for i, e in enumerate(out) if e.get("kind") not in PERMANENT), None)
        if i is None:
            break
        out.pop(i)
    return out


def merge(entries: list[dict], new: list[dict]) -> list[dict]:
    """Appends new entries: a run's record replaces its earlier one, a decision, question or
    answer already in the notebook is not added twice."""
    runs = {n.get("run_id") for n in new if n.get("kind") == "run" and n.get("run_id")}
    out = [e for e in entries if not (e.get("kind") == "run" and e.get("run_id") in runs)]
    seen = {(e.get("kind"), e.get("text")) for e in out if e.get("kind") in PERMANENT}
    for n in new:
        if not n.get("text"):
            continue
        key = (n["kind"], n["text"])
        if n["kind"] in PERMANENT and key in seen:
            continue
        seen.add(key)
        out.append(n)
    return prune(out)


def render(entries: list[dict]) -> str:
    """Markdown list for prompts and the run page, oldest first."""
    lines = []
    for e in entries:
        head = LABELS.get(e.get("kind"), e.get("kind") or "?")
        if e.get("run_id"):
            head += f" #{e['run_id']}"
        lines.append(f"- **{head}:** " + (e.get("text") or "").replace("\n", "\n  "))
    return "\n".join(lines)


async def load(session: AsyncSession, project_id: str, pr_number: int) -> ChainNotebook | None:
    return (
        await session.execute(
            select(ChainNotebook).where(
                ChainNotebook.project_id == project_id, ChainNotebook.pr_number == pr_number
            )
        )
    ).scalar_one_or_none()


async def add_entries(
    session: AsyncSession, project_id: str, pr_number: int, new: list[dict]
) -> None:
    """Merges ``new`` into the PR's notebook (created on first write) and commits."""
    if not new:
        return
    row = await load(session, project_id, pr_number)
    if row is None:
        row = ChainNotebook(project_id=project_id, pr_number=pr_number, entries=[])
        session.add(row)
    row.entries = merge(list(row.entries or []), new)
    row.updated_at = datetime.now(UTC)
    await session.commit()

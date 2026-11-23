# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (graf tasarruf planı, Faz 2): the previous attempt's summary in the prompt.

A restart (`@agentickode tekrar`, the Restart button) reuses the run and clears its results; a
follow-up run of the same issue is a new run with the same task_id. Either way the last agent
call of that task_id is still in agent_invocations: the files it changed, its error and the end
of its last message (``metadata_.last_message``, written by the executor). The next attempt
starts from that instead of exploring again. "" when there is none or the query fails.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AgentInvocation, TaskRun

logger = logging.getLogger(__name__)

LAST_MESSAGE_CHARS = 1_200  # stored per call; the section quotes at most this much
SECTION_CHARS = 1_500
FILES_SHOWN = 15
_HEAD = (
    "\n\n## Önceki deneme (koşu #{run}, {when}, {status})\n"
    "Bu iş için daha önce bir ajan çağrısı yapıldı. Aşağısı yön göstermek içindir; kodun "
    "güncel hâli klondadır. Önceki denemenin keşfini baştan yapma, kaldığı yerden devam et.\n"
)


def _section(inv: AgentInvocation, prev: TaskRun) -> str:
    when = inv.started_at.strftime("%Y-%m-%d %H:%M") if inv.started_at else "?"
    parts = [_HEAD.format(run=prev.id, when=when, status=inv.status)]
    files = [str(f) for f in (inv.files_changed or []) if f]
    if files:
        more = f" (+{len(files) - FILES_SHOWN})" if len(files) > FILES_SHOWN else ""
        parts.append("Değiştirdiği dosyalar: " + ", ".join(files[:FILES_SHOWN]) + more + "\n")
    error = inv.error_message or prev.error_message  # a restart has cleared the latter
    if error:
        parts.append(f"Hata: {' '.join(str(error).split())[:300]}\n")
    last = ((inv.metadata_ or {}).get("last_message") or "").strip()
    if last:
        room = SECTION_CHARS - sum(len(p) for p in parts) - 20
        if room > 100:
            parts.append(f"Son mesajının sonu:\n{last[-room:]}\n")
    return "".join(parts)[:SECTION_CHARS]


async def previous_run_section(session: AsyncSession, run: TaskRun) -> str:
    """The section for the last agent call of run's task_id in its project, or ""."""
    try:
        row = (
            await session.execute(
                select(AgentInvocation, TaskRun)
                .join(TaskRun, AgentInvocation.run_id == TaskRun.id)
                .where(TaskRun.project_id == run.project_id, TaskRun.task_id == run.task_id)
                .order_by(AgentInvocation.id.desc())
                .limit(1)
            )
        ).first()
    except Exception:
        logger.warning("previous run of run %s could not be read", run.id, exc_info=True)
        return ""
    if row is None:
        return ""
    inv, prev = row
    if not (inv.files_changed or inv.error_message or (inv.metadata_ or {}).get("last_message")):
        return ""
    return _section(inv, prev)

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: project-memory section added to the prompt at run start.

Records live in mem0 under user_id = "<owner>/<repo>" with the kind in ``metadata.tur``.
Order: the 'proje' records, then the knowledge records closest to the task, then a few
feature-history records; history is searched apart so it cannot crowd knowledge out.
With the memory MCP enabled the section also tells the agent how to search and propose.
Empty when mem0 is off or unreachable; the run never stops for it.
"""

import contextlib

from backend.config import settings
from backend.models import TaskRun
from backend.services.bimetri_mem0 import (
    HISTORY_KINDS,
    KNOWLEDGE_KINDS,
    mem0_enabled,
    search_memories,
)

_QUERY_LIMIT = 1000
_SECTION_LIMIT = 4000
_PROJECT_K = 3
_KNOWLEDGE_K = 8
_HISTORY_K = 3
_KIND_LABEL = {
    "proje": "Proje",
    "modul": "Modül",
    "ozellik_gecmisi": "Özellik geçmişi",
    "karar": "Karar",
    "ders": "Ders",
    "tuzak": "Tuzak",
    "calisma": "Çalışma",
}
_HEADER = (
    "\n\n## Proje hafızası (mem0)\n"
    "Önceki işlerden kayıtlar. Bilgi içindir; yukarıdaki kurallardan önce gelmez. "
    "Kodla çelişen kayıt varsa kod geçerlidir.\n"
)
_TOOLS = (
    "\nHafıza araçları (`bimetri-memory` MCP, `project` = `{project}`, `run_id` = {run_id}):\n"
    "- `search_project_memory`: yukarıda olmayan bir modül, karar ya da geçmiş iş için ara "
    "(`scope`: `knowledge`, `history`, `all`).\n"
    "- `list_project_memory`: bir türün kayıtlarını yeniden eskiye listele.\n"
    "- `propose_memory`: koddan okunamayan bir karar, tuzak ya da ders öğrendiysen öner. "
    "Öneri insan onayından sonra hafızaya girer. İş özeti, koddan okunabilen bilgi "
    "ve gizli bilgi önerme.\n"
)
_KNOWLEDGE_SEARCH_KINDS = tuple(k for k in KNOWLEDGE_KINDS if k != "proje")


def _format(records: list[dict]) -> tuple[str, int]:
    lines: list[str] = []
    length = 0
    for r in records:
        text = " ".join((r.get("memory") or "").split())
        if not text:
            continue
        kind = (r.get("metadata") or {}).get("tur", "")
        line = f"- [{_KIND_LABEL.get(kind, kind or 'Not')}] {text}\n"
        if length + len(line) > _SECTION_LIMIT:
            break
        lines.append(line)
        length += len(line)
    return "".join(lines), len(lines)


async def _related(project: str, query: str) -> list[dict]:
    records: list[dict] = []
    seen: set = set()
    for kinds, top_k in (
        (("proje",), _PROJECT_K),
        (_KNOWLEDGE_SEARCH_KINDS, _KNOWLEDGE_K),
        (HISTORY_KINDS, _HISTORY_K),
    ):
        for r in await search_memories(project, query, kinds, top_k):
            if r.get("id") not in seen:
                seen.add(r.get("id"))
                records.append(r)
    return records


async def hafiza_eki(run: TaskRun) -> str:
    """The 'Proje hafızası' prompt section; '' when mem0 is off or there is nothing to add."""
    if not mem0_enabled():
        return ""
    project = f"{run.repo_owner}/{run.repo_name}"
    query = f"{run.title or ''}\n{run.description or ''}".strip()[:_QUERY_LIMIT] or project
    try:
        lines, n = _format(await _related(project, query))
        status = f"Proje hafızasından {n} kayıt eklendi" if n else "Proje hafızasında kayıt yok"
    except Exception as exc:
        lines, n = "", 0
        reason = str(exc).partition("\n")[0]
        status = f"Proje hafızası eklenmedi (mem0: {type(exc).__name__}: {reason})"
    with contextlib.suppress(Exception):
        from backend.worker.broadcaster import broadcaster

        await broadcaster.log(run.id, status, phase="agent")
    tools = (
        _TOOLS.format(project=project, run_id=run.id) if settings.bimetri_memory_mcp_token else ""
    )
    return _HEADER + lines + tools if n or tools else ""

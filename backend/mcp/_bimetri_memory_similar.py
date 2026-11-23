# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: duplicate check for agent memory proposals.

Before a proposal is queued, the memory is searched for records that already say nearly the
same thing. Measured on platform-backend (mem0 v2.2.1, text-embedding-3-small): the same rule
reworded scored 0.62-0.85 cosine, a record searched with its own text 0.91, unrelated text
0.29-0.44. Related but new facts can also pass 0.60, so the agent may still propose with
``force``; it then sees the records and the reviewer sees them on the card.
"""

import logging
import uuid

from fastmcp.exceptions import ToolError

from backend.services.bimetri_mem0 import KNOWLEDGE_KINDS, get_memory, similar_memories

logger = logging.getLogger("agentickode.mcp.bimetri_memory_similar")

MIN_SIMILARITY = 0.60
MAX_SIMILAR = 3


def compact(row: dict) -> dict:
    """The fields a proposal keeps of a record: enough to show and to pick it as a replacement."""
    out = {
        "id": str(row.get("id", "")),
        "text": " ".join(str(row.get("memory") or "").split()),
        "kind": (row.get("metadata") or {}).get("tur"),
    }
    if isinstance(row.get("similarity"), int | float):
        out["similarity"] = round(row["similarity"], 3)
    return out


async def find_similar(project: str, text: str) -> list[dict] | None:
    """Knowledge records close to ``text``; None when mem0 could not be asked (never blocks)."""
    try:
        rows = await similar_memories(project, text, KNOWLEDGE_KINDS, MIN_SIMILARITY)
    except Exception:
        logger.warning("mem0 similarity search failed for %s", project, exc_info=True)
        return None
    return [compact(r) for r in rows[:MAX_SIMILAR]]


async def replaced_record(project: str, memory_id: str) -> dict:
    """The project's record that a proposal will replace; refuses ids of other projects."""
    try:
        uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(f"replaces must be a record id, got {memory_id!r}") from None
    try:
        row = await get_memory(memory_id)
    except Exception as e:
        raise ToolError(f"mem0 read failed: {e}") from e
    if row is None or row.get("user_id") != project:
        raise ToolError(f"{memory_id} is not a record of {project}")
    return compact(row)

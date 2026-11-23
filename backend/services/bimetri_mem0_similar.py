# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: duplicate check for memory proposals (agent and merge).

Before a proposal is queued, the memory is searched for records that already say nearly the
same thing. Measured on platform-backend (mem0 v2.2.1, text-embedding-3-small): the same rule
reworded scored 0.62-0.85 cosine, a record searched with its own text 0.91, unrelated text
0.29-0.44. Related but new facts can also pass 0.60, so the reviewer sees the records on the
card and decides.

The result kept on a proposal: a list (empty when nothing passed the threshold) or None when
mem0 could not be asked, so the card can tell "none found" from "not checked".
"""

import logging

from backend.services.bimetri_mem0 import KNOWLEDGE_KINDS, similar_memories

logger = logging.getLogger("agentickode.bimetri.mem0_similar")

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

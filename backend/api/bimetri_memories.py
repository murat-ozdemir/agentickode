# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: read-only view of one project's mem0 records.

Records are stored by the merge webhook, approved proposals and scripts/bimetri tooling;
``metadata`` keys (tur, kaynak, pr, tarih) are kept as written and exposed under English names.
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.services.bimetri_mem0 import list_memories, mem0_enabled

logger = logging.getLogger("agentickode.api.bimetri_memories")
router = APIRouter(prefix="/bimetri/memories", tags=["bimetri"])


class MemoryRecordResponse(BaseModel):
    id: str
    text: str
    kind: str | None = None
    source: str | None = None
    pr_number: int | None = None
    date: str | None = None
    created_at: str | None = None


def _to_record(raw: dict) -> MemoryRecordResponse:
    meta = raw.get("metadata") or {}
    pr = meta.get("pr")
    return MemoryRecordResponse(
        id=str(raw.get("id", "")),
        text=str(raw.get("memory") or ""),
        kind=meta.get("tur"),
        source=meta.get("kaynak"),
        pr_number=int(pr) if str(pr).isdigit() else None,
        date=meta.get("tarih"),
        created_at=raw.get("created_at"),
    )


@router.get("")
async def list_records(
    project: str = Query(min_length=1),
    kind: str | None = None,
) -> list[MemoryRecordResponse]:
    """Newest first; ``kind`` filters on ``metadata.tur`` (e.g. karar, tuzak)."""
    if not mem0_enabled():
        raise HTTPException(status_code=503, detail="mem0 is not configured")
    try:
        rows = await list_memories(project)
    except Exception as e:
        logger.warning("mem0 read failed for %s", project, exc_info=True)
        raise HTTPException(status_code=502, detail=f"mem0 read failed: {e}") from e
    records = [_to_record(r) for r in rows]
    if kind:
        records = [r for r in records if r.kind == kind]
    return sorted(records, key=lambda r: r.created_at or "", reverse=True)

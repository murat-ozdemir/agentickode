# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: review the memory proposals made on PR merges or by agents.

Approving writes the (possibly edited) text to mem0 under the project's user_id; rejecting
only marks the row. Decided proposals are kept so the LLM does not propose them again.
"""

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import MemoryProposal
from backend.repositories.memory_proposal_repo import MemoryProposalRepository
from backend.services.bimetri_mem0 import add_memory, mem0_enabled
from backend.worker.flow._bimetri_proposals import KIND_TO_TUR

logger = logging.getLogger("agentickode.api.bimetri_memory_proposals")
router = APIRouter(prefix="/bimetri/memory-proposals", tags=["bimetri"])

Kind = Literal["lesson", "pitfall", "decision"]
Status = Literal["pending", "approved", "rejected"]


class MemoryProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project: str
    pr_number: int | None = None
    source: str = "merge"
    run_id: int | None = None
    kind: str
    text: str
    status: str
    mem0_id: str | None = None
    created_at: datetime | None = None
    decided_at: datetime | None = None


class MemoryProposalUpdate(BaseModel):
    kind: Kind | None = None
    text: str | None = Field(default=None, min_length=1, max_length=2000)


async def _pending(repo: MemoryProposalRepository, proposal_id: int) -> MemoryProposal:
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal is already {proposal.status}")
    return proposal


@router.get("")
async def list_proposals(
    status: Status | None = None,
    project: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[MemoryProposalResponse]:
    rows = await MemoryProposalRepository(db).list_proposals(status=status, project=project)
    return [MemoryProposalResponse.model_validate(r) for r in rows]


@router.patch("/{proposal_id}")
async def update_proposal(
    proposal_id: int, body: MemoryProposalUpdate, db: AsyncSession = Depends(get_db)
) -> MemoryProposalResponse:
    proposal = await _pending(MemoryProposalRepository(db), proposal_id)
    if body.kind is not None:
        proposal.kind = body.kind  # type: ignore[assignment]
    if body.text is not None:
        proposal.text = body.text.strip()  # type: ignore[assignment]
    await db.commit()
    return MemoryProposalResponse.model_validate(proposal)


@router.post("/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: int, db: AsyncSession = Depends(get_db)
) -> MemoryProposalResponse:
    proposal = await _pending(MemoryProposalRepository(db), proposal_id)
    if not mem0_enabled():
        raise HTTPException(status_code=503, detail="mem0 is not configured")
    now = datetime.now(UTC)
    metadata = {
        "tur": KIND_TO_TUR[str(proposal.kind)],
        "kaynak": "agent" if proposal.source == "agent" else "proposal",
        "tarih": now.date().isoformat(),
    }
    if proposal.pr_number is not None:
        metadata["pr"] = proposal.pr_number
    try:
        mem0_id = await add_memory(str(proposal.project), str(proposal.text), metadata)
    except Exception as e:
        logger.warning("mem0 write failed for proposal %s", proposal_id, exc_info=True)
        raise HTTPException(status_code=502, detail=f"mem0 write failed: {e}") from e
    proposal.status = "approved"  # type: ignore[assignment]
    proposal.mem0_id = mem0_id  # type: ignore[assignment]
    proposal.decided_at = now  # type: ignore[assignment]
    await db.commit()
    return MemoryProposalResponse.model_validate(proposal)


@router.post("/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: int, db: AsyncSession = Depends(get_db)
) -> MemoryProposalResponse:
    proposal = await _pending(MemoryProposalRepository(db), proposal_id)
    proposal.status = "rejected"  # type: ignore[assignment]
    proposal.decided_at = datetime.now(UTC)  # type: ignore[assignment]
    await db.commit()
    return MemoryProposalResponse.model_validate(proposal)

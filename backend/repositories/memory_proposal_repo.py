# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: repository for project-memory proposals."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import MemoryProposal


class MemoryProposalRepository:
    """Encapsulates all MemoryProposal database queries."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_proposals(self, status: str | None = None, project: str | None = None):
        query = select(MemoryProposal).order_by(MemoryProposal.id.desc())
        if status:
            query = query.where(MemoryProposal.status == status)
        if project:
            query = query.where(MemoryProposal.project == project)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, proposal_id: int) -> MemoryProposal | None:
        return await self._session.get(MemoryProposal, proposal_id)

    async def exists_for_pr(self, project: str, pr_number: int) -> bool:
        """Whether the merge of this PR was already handled; agent proposals do not count."""
        result = await self._session.execute(
            select(MemoryProposal.id)
            .where(
                MemoryProposal.project == project,
                MemoryProposal.pr_number == pr_number,
                MemoryProposal.source == "merge",
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def count_for_run(self, run_id: int) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(MemoryProposal).where(MemoryProposal.run_id == run_id)
        )
        return int(result.scalar_one())

    async def pending_texts(self, project: str) -> set[str]:
        result = await self._session.execute(
            select(MemoryProposal.text).where(
                MemoryProposal.project == project, MemoryProposal.status == "pending"
            )
        )
        return set(result.scalars().all())

    async def add_all(self, proposals: list[MemoryProposal]) -> None:
        self._session.add_all(proposals)
        await self._session.flush()

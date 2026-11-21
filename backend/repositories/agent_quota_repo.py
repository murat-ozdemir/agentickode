# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: repository for the agent subscription accounts and their limits."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AgentQuotaAccount


class AgentQuotaRepository:
    """Encapsulates the AgentQuotaAccount queries."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_all(self) -> list[AgentQuotaAccount]:
        result = await self._session.execute(
            select(AgentQuotaAccount).order_by(
                AgentQuotaAccount.provider, AgentQuotaAccount.email, AgentQuotaAccount.id
            )
        )
        return list(result.scalars().all())

    def add(self, account: AgentQuotaAccount) -> None:
        self._session.add(account)

    async def commit(self) -> None:
        await self._session.commit()

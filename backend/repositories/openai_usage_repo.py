# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: repository for OpenAI credits and daily spend."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import OpenAICredit, OpenAIDailyCost


class OpenAIUsageRepository:
    """Encapsulates the OpenAICredit and OpenAIDailyCost queries."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_credits(self) -> list[OpenAICredit]:
        result = await self._session.execute(
            select(OpenAICredit).order_by(OpenAICredit.credited_on.desc(), OpenAICredit.id.desc())
        )
        return list(result.scalars().all())

    async def get_credit(self, credit_id: int) -> OpenAICredit | None:
        return await self._session.get(OpenAICredit, credit_id)

    async def add_credit(self, amount_usd: Decimal, credited_on: date) -> OpenAICredit:
        credit = OpenAICredit(amount_usd=amount_usd, credited_on=credited_on)
        self._session.add(credit)
        await self._session.commit()
        await self._session.refresh(credit)
        return credit

    async def save(self, credit: OpenAICredit) -> OpenAICredit:
        await self._session.commit()
        await self._session.refresh(credit)
        return credit

    async def delete_credit(self, credit: OpenAICredit) -> None:
        await self._session.delete(credit)
        await self._session.commit()

    async def first_credit_on(self) -> date | None:
        return await self._session.scalar(select(func.min(OpenAICredit.credited_on)))

    async def spend_since(self, day: date) -> Decimal:
        """Spend of every stored UTC day from ``day`` on."""
        result = await self._session.execute(
            select(OpenAIDailyCost.amount_usd).where(OpenAIDailyCost.day >= day)
        )
        return sum((Decimal(str(v)) for v in result.scalars().all()), Decimal(0))

    async def days_since(self, day: date) -> list[tuple[date, Decimal]]:
        """Stored UTC days from ``day`` on, oldest first."""
        result = await self._session.execute(
            select(OpenAIDailyCost.day, OpenAIDailyCost.amount_usd)
            .where(OpenAIDailyCost.day >= day)
            .order_by(OpenAIDailyCost.day)
        )
        return [(d, Decimal(str(v))) for d, v in result.all()]

    async def store_days(self, days: dict[date, Decimal], fetched_at: datetime) -> None:
        """Overwrite the given days with what the Costs API reported now."""
        for day, amount in days.items():
            await self._session.merge(
                OpenAIDailyCost(day=day, amount_usd=amount, fetched_at=fetched_at)
            )
        await self._session.commit()

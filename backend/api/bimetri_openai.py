# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: OpenAI API spend card (Dashboard) and the hand-entered credits behind it.

A new credit entry clears the quota alert and refreshes the spend, since an entry dated before
the stored days widens the range the remaining balance needs.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.repositories.openai_usage_repo import OpenAIUsageRepository
from backend.services import bimetri_openai_usage
from backend.services.bimetri_openai_alert import clear_alert

router = APIRouter(prefix="/bimetri/openai", tags=["bimetri"])


class QuotaAlert(BaseModel):
    code: str
    source: str
    at: str


class OpenAIUsageSummary(BaseModel):
    enabled: bool
    month_start: date
    month_spend_usd: float
    credits_total_usd: float
    first_credit_on: date | None = None
    spent_since_first_credit_usd: float | None = None
    remaining_usd: float | None = None
    last_sync_at: str | None = None
    sync_error: str | None = None
    alert: QuotaAlert | None = None


class CreditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount_usd: float
    credited_on: date
    created_at: datetime | None = None


class CreditCreate(BaseModel):
    amount_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    credited_on: date = Field(default_factory=lambda: datetime.now(UTC).date())


class CreditUpdate(BaseModel):
    amount_usd: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    credited_on: date | None = None


async def _refresh(session: AsyncSession) -> None:
    if bimetri_openai_usage.usage_enabled():
        await bimetri_openai_usage.sync(session)


@router.get("/summary")
async def get_summary(db: AsyncSession = Depends(get_db)) -> OpenAIUsageSummary:
    return OpenAIUsageSummary(**await bimetri_openai_usage.summary(db))


@router.post("/sync")
async def sync_now(db: AsyncSession = Depends(get_db)) -> OpenAIUsageSummary:
    if not bimetri_openai_usage.usage_enabled():
        raise HTTPException(409, "OPENAI_ADMIN_KEY is not set")
    await bimetri_openai_usage.sync(db)
    return OpenAIUsageSummary(**await bimetri_openai_usage.summary(db))


@router.get("/credits")
async def list_credits(db: AsyncSession = Depends(get_db)) -> list[CreditResponse]:
    credits = await OpenAIUsageRepository(db).list_credits()
    return [CreditResponse.model_validate(c) for c in credits]


@router.post("/credits", status_code=201)
async def add_credit(payload: CreditCreate, db: AsyncSession = Depends(get_db)) -> CreditResponse:
    credit = await OpenAIUsageRepository(db).add_credit(payload.amount_usd, payload.credited_on)
    await clear_alert(db)
    await _refresh(db)
    return CreditResponse.model_validate(credit)


@router.patch("/credits/{credit_id}")
async def update_credit(
    credit_id: int, payload: CreditUpdate, db: AsyncSession = Depends(get_db)
) -> CreditResponse:
    repo = OpenAIUsageRepository(db)
    credit = await repo.get_credit(credit_id)
    if credit is None:
        raise HTTPException(404, "Credit entry not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(credit, field, value)
    credit = await repo.save(credit)
    await _refresh(db)
    return CreditResponse.model_validate(credit)


@router.delete("/credits/{credit_id}", status_code=204)
async def delete_credit(credit_id: int, db: AsyncSession = Depends(get_db)) -> None:
    repo = OpenAIUsageRepository(db)
    credit = await repo.get_credit(credit_id)
    if credit is None:
        raise HTTPException(404, "Credit entry not found")
    await repo.delete_credit(credit)

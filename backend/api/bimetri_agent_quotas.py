# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: 5-hour / weekly limits of the agent subscription accounts (Dashboard strip)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.bimetri_agent_quota import service

router = APIRouter(prefix="/bimetri/agent-quotas", tags=["bimetri"])


class QuotaWindowOut(BaseModel):
    key: str
    label: str
    minutes: int | None = None
    used_percent: float
    resets_at: str | None = None


class QuotaWorkerOut(BaseModel):
    server_id: int
    server_name: str
    user: str


class QuotaAccountOut(BaseModel):
    id: int
    provider: str
    email: str | None = None
    plan: str | None = None
    org_name: str | None = None
    windows: list[QuotaWindowOut] = []
    limit_reached: bool = False
    workers: list[QuotaWorkerOut] = []
    error: str | None = None
    observed_at: str | None = None
    checked_at: str | None = None


class ProbeErrorOut(BaseModel):
    server_name: str
    error: str


class AgentQuotaSummary(BaseModel):
    accounts: list[QuotaAccountOut] = []
    last_sync_at: str | None = None
    errors: list[ProbeErrorOut] = []


@router.get("")
async def get_quotas(db: AsyncSession = Depends(get_db)) -> AgentQuotaSummary:
    return AgentQuotaSummary(**await service.summary(db))


@router.post("/sync")
async def sync_quotas(db: AsyncSession = Depends(get_db)) -> AgentQuotaSummary:
    await service.collect(db)
    return AgentQuotaSummary(**await service.summary(db))

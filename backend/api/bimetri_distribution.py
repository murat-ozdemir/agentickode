# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Task Distribution card (Dashboard) — runs per server, agent, model and so on."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.repositories.run_distribution_repo import RunDistributionRepository
from backend.services import bimetri_run_distribution as dist

router = APIRouter(prefix="/bimetri/analytics", tags=["bimetri"])

RangeKey = Literal["7d", "30d", "all"]
Dimension = Literal["server", "agent", "model", "difficulty", "type", "outcome"]


class DistributionDay(BaseModel):
    date: str
    total: int
    by: dict[str, dict[str, int]]


class DistributionItem(BaseModel):
    name: str
    count: int
    ok_pct: int | None = None


class RunDistribution(BaseModel):
    range: RangeKey
    total: int
    since: str
    days: list[DistributionDay]
    groups: dict[str, list[DistributionItem]]


@router.get("/distribution", response_model=RunDistribution)
async def get_distribution(
    range_key: RangeKey = Query("all", alias="range"),
    db: AsyncSession = Depends(get_db),
) -> RunDistribution:
    today = datetime.now(UTC).date()
    since = dist.since_for(range_key, today)
    rows = await RunDistributionRepository(db).list_rows(since)
    return RunDistribution(range=range_key, **dist.build(rows, since, today))


async def matching_run_ids(
    db: AsyncSession, range_key: RangeKey, dim: Dimension, value: str
) -> list[int]:
    """Run ids behind one row of the card; the Runs list filters on these."""
    since = dist.since_for(range_key, datetime.now(UTC).date())
    rows = await RunDistributionRepository(db).list_rows(since)
    return dist.matching_ids(rows, dim, value)

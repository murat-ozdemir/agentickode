# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): Code graph card (Dashboard) — graph use and savings."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.bimetri_distribution import RangeKey
from backend.database import get_db
from backend.repositories.graph_usage_repo import GraphUsageRepository
from backend.services import bimetri_graph_usage as usage
from backend.services.bimetri_run_distribution import since_for

router = APIRouter(prefix="/bimetri/analytics", tags=["bimetri"])


class GraphSums(BaseModel):
    runs: int
    calls: int
    saved_tokens: int
    saved_usd: float
    returned_chars: int
    full_chars: int
    saved_pct: int | None = None


class GraphWorker(GraphSums):
    name: str


class GraphDay(BaseModel):
    date: str
    saved_tokens: int


class GraphUsage(BaseModel):
    range: RangeKey
    total_runs: int
    since: str
    totals: GraphSums
    agents: dict[str, int]
    days: list[GraphDay]
    workers: list[GraphWorker]


@router.get("/graph", response_model=GraphUsage)
async def get_graph_usage(
    range_key: RangeKey = Query("7d", alias="range"),
    db: AsyncSession = Depends(get_db),
) -> GraphUsage:
    today = datetime.now(UTC).date()
    since = since_for(range_key, today)
    rows = await GraphUsageRepository(db).list_rows(since)
    return GraphUsage(range=range_key, **usage.build(rows, since, today))

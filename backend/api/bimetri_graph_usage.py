# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): Code graph card (Dashboard) — graph use and savings."""

from datetime import UTC, datetime, time

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.bimetri_distribution import RangeKey
from backend.database import get_db
from backend.repositories.graph_usage_repo import GraphUsageRepository
from backend.services import bimetri_graph_usage as usage
from backend.services import bimetri_run_tokens as run_tokens
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


class RunTokens(BaseModel):
    """Graph calls' tokens against their pre-graph baseline (bimetri_run_tokens)."""

    graph_calls: int
    compared: int
    same_task: int
    same_repo: int
    actual_tokens: int
    baseline_tokens: int
    saved_pct: int | None = None
    turns_per_call: float | None = None


class GraphUsage(BaseModel):
    range: RangeKey
    total_runs: int
    since: str
    totals: GraphSums
    agents: dict[str, int]
    days: list[GraphDay]
    workers: list[GraphWorker]
    run_tokens: RunTokens


@router.get("/graph", response_model=GraphUsage)
async def get_graph_usage(
    range_key: RangeKey = Query("7d", alias="range"),
    db: AsyncSession = Depends(get_db),
) -> GraphUsage:
    today = datetime.now(UTC).date()
    since = since_for(range_key, today)
    repo = GraphUsageRepository(db)
    rows = await repo.list_rows(since)
    start = datetime.combine(since, time.min, tzinfo=UTC) if since else None
    tokens = run_tokens.build(await repo.list_token_rows(), start)
    return GraphUsage(
        range=range_key, run_tokens=RunTokens(**tokens), **usage.build(rows, since, today)
    )

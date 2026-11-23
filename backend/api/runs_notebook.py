# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 7): the chain notebook of a run's PR, for the run page."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import TaskRun
from backend.worker.phases._bimetri_notebook import load
from backend.worker.phases._bimetri_notebook_record import run_pr_number

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}/notebook")
async def get_run_notebook(run_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    run = await db.get(TaskRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    pr_number = run_pr_number(run)
    row = await load(db, run.project_id, pr_number) if pr_number else None
    return {"pr_number": pr_number, "entries": list(row.entries) if row else []}

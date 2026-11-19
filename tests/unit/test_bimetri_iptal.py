# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a cancel made while the agent works is not overwritten."""

from unittest.mock import AsyncMock

from sqlalchemy import update

from backend.models import TaskRun
from backend.worker.flow._bimetri_iptal import was_cancelled


async def _running_run(db_session, make_task_run) -> TaskRun:
    run = make_task_run(status="running")
    db_session.add(run)
    await db_session.commit()
    return run


async def _cancel_elsewhere(db_session, run: TaskRun) -> None:
    """Like the cancel endpoint: write the DB row, leave the executor's object stale."""
    stmt = update(TaskRun).where(TaskRun.id == run.id).values(status="cancelled")
    await db_session.execute(stmt.execution_options(synchronize_session=False))
    await db_session.commit()


class TestWasCancelled:
    async def test_detects_cancel_made_in_another_session(
        self, db_session, seed_proj1, make_task_run
    ):
        run = await _running_run(db_session, make_task_run)
        await _cancel_elsewhere(db_session, run)
        assert run.status == "running"

        assert await was_cancelled(run, db_session) is True
        assert run.status == "cancelled"

    async def test_running_run_is_not_cancelled(self, db_session, seed_proj1, make_task_run):
        run = await _running_run(db_session, make_task_run)

        assert await was_cancelled(run, db_session) is False
        assert run.status == "running"

    async def test_broken_session_counts_as_not_cancelled(
        self, db_session, seed_proj1, make_task_run
    ):
        run = await _running_run(db_session, make_task_run)
        broken = AsyncMock()
        broken.no_autoflush = db_session.no_autoflush
        broken.execute.side_effect = RuntimeError("db down")

        assert await was_cancelled(run, broken) is False

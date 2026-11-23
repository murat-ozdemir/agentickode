# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 7): GET /api/runs/{id}/notebook."""

import pytest

from backend.worker.phases._bimetri_notebook import add_entries, entry

pytestmark = pytest.mark.usefixtures("seed_proj1")


async def _save(db_session, run):
    db_session.add(run)
    await db_session.commit()
    return run.id


async def test_returns_the_prs_notebook(client, db_session, make_task_run):
    run_id = await _save(db_session, make_task_run(task_source_meta={"pr_number": 5}))
    await add_entries(db_session, "proj-1", 5, [entry("decision", "a", run_id)])

    data = (await client.get(f"/api/runs/{run_id}/notebook")).json()

    assert data["pr_number"] == 5
    assert [(e["kind"], e["text"]) for e in data["entries"]] == [("decision", "a")]


async def test_run_without_pr_has_an_empty_notebook(client, db_session, make_task_run):
    run_id = await _save(db_session, make_task_run())

    data = (await client.get(f"/api/runs/{run_id}/notebook")).json()

    assert data == {"pr_number": None, "entries": []}


async def test_unknown_run_is_404(client):
    assert (await client.get("/api/runs/999/notebook")).status_code == 404

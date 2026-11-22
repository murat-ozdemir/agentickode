# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): Code graph card endpoint."""

import pytest

from backend.models import AgentInvocation, WorkspaceServer

pytestmark = pytest.mark.usefixtures("seed_proj1")

GRAPH = {"calls": 3, "saved_tokens": 2500, "returned_chars": 1000, "full_chars": 11000}


@pytest.fixture()
async def seeded(db_session, make_task_run):
    ws = WorkspaceServer(
        name="worker-1",
        hostname="10.0.0.1",
        port=22,
        username="root",
        workspace_root="/workspaces",
        status="online",
    )
    db_session.add(ws)
    await db_session.flush()
    runs = [make_task_run(task_id=f"T-{i}", workspace_server_id=ws.id) for i in range(2)]
    db_session.add_all(runs)
    await db_session.flush()
    db_session.add_all(
        [
            AgentInvocation(run_id=runs[0].id, agent_name="codex", metadata_={"graph": GRAPH}),
            AgentInvocation(run_id=runs[1].id, agent_name="claude", metadata_={"model": "x"}),
        ]
    )
    await db_session.commit()


class TestGraphUsageApi:
    async def test_sums_graph_blocks_by_worker(self, client, seeded):
        resp = await client.get("/api/bimetri/analytics/graph", params={"range": "7d"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_runs"] == 2 and len(body["days"]) == 7
        assert body["totals"]["runs"] == 1 and body["totals"]["saved_tokens"] == 2500
        assert body["totals"]["saved_pct"] == 91
        assert body["agents"] == {"codex": 1}
        assert [(w["name"], w["calls"]) for w in body["workers"]] == [("worker-1", 3)]

    async def test_rejects_unknown_range(self, client):
        resp = await client.get("/api/bimetri/analytics/graph", params={"range": "1y"})
        assert resp.status_code == 422

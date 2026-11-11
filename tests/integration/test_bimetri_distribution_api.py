# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Task Distribution endpoint and the Runs list filter built on it."""

import pytest

from backend.models import AgentInvocation, WorkspaceServer

pytestmark = pytest.mark.usefixtures("seed_proj1")


@pytest.fixture()
async def seeded(db_session, make_task_run):
    ws = WorkspaceServer(
        name="agent-1",
        hostname="10.0.0.1",
        port=22,
        username="root",
        workspace_root="/workspaces",
        status="online",
    )
    db_session.add(ws)
    await db_session.flush()
    runs = [
        make_task_run(
            task_id=f"T-{i}",
            status=status,
            workspace_server_id=ws.id,
            task_source_meta={"labels": [f"difficulty/{diff}"]},
        )
        for i, (status, diff) in enumerate([("completed", "easy"), ("failed", "hard")])
    ]
    runs.append(make_task_run(task_id="T-2", status="pending"))
    db_session.add_all(runs)
    await db_session.flush()
    for run, agent, model in [(runs[0], "codex", "gpt-6.1-terra"), (runs[1], "claude", None)]:
        db_session.add(AgentInvocation(run_id=run.id, agent_name=agent, metadata_={"model": model}))
    await db_session.commit()
    return runs


class TestDistributionApi:
    async def test_groups_runs_by_dimension(self, client, seeded):
        resp = await client.get("/api/bimetri/analytics/distribution", params={"range": "7d"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["range"] == "7d"
        assert body["total"] == 3
        assert len(body["days"]) == 7
        groups = body["groups"]
        assert groups["server"] == [
            {"name": "agent-1", "count": 2, "ok_pct": 50},
            {"name": "no server", "count": 1, "ok_pct": None},
        ]
        assert {i["name"]: i["count"] for i in groups["model"]} == {
            "gpt-6.1-terra": 1,
            "unknown": 1,
        }

    async def test_rejects_unknown_range(self, client):
        resp = await client.get("/api/bimetri/analytics/distribution", params={"range": "1y"})
        assert resp.status_code == 422


class TestRunsFilter:
    async def test_filters_runs_by_card_row(self, client, seeded):
        resp = await client.get("/api/runs", params={"dist_dim": "agent", "dist_value": "codex"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == seeded[0].id

    async def test_sentinel_value_matches_runs_without_calls(self, client, seeded):
        resp = await client.get(
            "/api/runs", params={"dist_dim": "agent", "dist_value": "no agent call"}
        )
        assert [r["id"] for r in resp.json()["items"]] == [seeded[2].id]

    async def test_rejects_unknown_dimension(self, client):
        resp = await client.get("/api/runs", params={"dist_dim": "color", "dist_value": "x"})
        assert resp.status_code == 422

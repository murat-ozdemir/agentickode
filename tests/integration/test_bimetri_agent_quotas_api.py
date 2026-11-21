# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: GET/POST /api/bimetri/agent-quotas."""

from unittest.mock import patch

from backend.models import WorkspaceServer
from backend.services.bimetri_agent_quota import service
from backend.services.bimetri_agent_quota.probe import ProbeResult

URL = "/api/bimetri/agent-quotas"

CLAUDE = {
    "account": {"accountUuid": "acc-1", "emailAddress": "dev@example.com"},
    "plan": "pro",
    "usage": {"five_hour": {"utilization": 72.0, "resets_at": "2026-11-22T10:00:00+00:00"}},
}


class TestAgentQuotasApi:
    async def test_empty_before_the_first_round(self, client):
        resp = await client.get(URL)
        assert resp.status_code == 200
        assert resp.json() == {"accounts": [], "last_sync_at": None, "errors": []}

    async def test_sync_probes_the_servers_and_returns_the_accounts(self, client, db_session):
        server = WorkspaceServer(name="worker-1", hostname="10.0.0.1")
        db_session.add(server)
        await db_session.commit()

        async def fake_probe(server):
            return ProbeResult("coder", {"claude": CLAUDE})

        with patch.object(service, "probe_server", fake_probe):
            resp = await client.post(f"{URL}/sync")
        assert resp.status_code == 200
        body = resp.json()
        assert body["last_sync_at"] and body["errors"] == []
        [account] = body["accounts"]
        assert (account["provider"], account["email"], account["plan"]) == (
            "claude",
            "dev@example.com",
            "pro",
        )
        assert account["windows"] == [
            {
                "key": "five_hour",
                "label": "5h",
                "minutes": 300,
                "used_percent": 72.0,
                "resets_at": "2026-11-22T10:00:00+00:00",
                "scope": None,
            }
        ]
        assert account["credits"] is None
        assert account["workers"] == [
            {"server_id": server.id, "server_name": "worker-1", "user": "coder"}
        ]
        assert (await client.get(URL)).json()["accounts"] == body["accounts"]

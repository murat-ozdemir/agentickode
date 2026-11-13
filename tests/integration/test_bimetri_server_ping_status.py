# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: the servers-page ping must not mark a failed setup online."""

from unittest.mock import patch

from httpx import AsyncClient

from backend.models import WorkspaceServer


def _server(name: str, status: str) -> WorkspaceServer:
    return WorkspaceServer(
        name=name,
        hostname="localhost",
        server_type="local",
        port=0,
        username="root",
        workspace_root="/workspaces",
        status=status,
    )


async def _reachable(server):
    return int(server.id), True, None


class TestPingKeepsSetupStatus:
    async def test_reachable_failed_setup_stays_failed(self, client: AsyncClient, db_session):
        db_session.add_all([_server("platform", "setup_failed"), _server("worker-1", "offline")])
        await db_session.commit()

        with patch("backend.api.servers.workspace_servers._ping_server", _reachable):
            resp = await client.get("/api/workspace-servers?check=true")

        assert resp.status_code == 200
        statuses = {s["name"]: s["status"] for s in resp.json()}
        assert statuses == {"platform": "setup_failed", "worker-1": "online"}

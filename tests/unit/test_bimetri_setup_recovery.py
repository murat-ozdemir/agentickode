# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a setup interrupted by a backend restart is shown as failed."""

from backend.models import WorkspaceServer
from backend.services.workspace._bimetri_setup_recovery import (
    INTERRUPTED,
    fail_interrupted_setups,
)

T = "2026-11-13T14:31:30+00:00"


def _server(name, status, log):
    return WorkspaceServer(
        name=name,
        hostname="localhost",
        server_type="local",
        port=0,
        username="root",
        workspace_root="/workspaces",
        status=status,
        setup_log=log,
    )


class TestFailInterruptedSetups:
    async def test_running_step_becomes_failed_and_others_stay(self, db_session):
        stuck = _server(
            "platform",
            "setting_up",
            {
                "ssh_test": {"status": "skipped", "error": None, "timestamp": T},
                "install_system_deps": {"status": "running", "error": None, "timestamp": T},
                "create_worker_user": {"status": "pending", "error": None, "timestamp": T},
            },
        )
        done = _server("worker-1", "online", {"ssh_test": {"status": "running", "timestamp": T}})
        db_session.add_all([stuck, done])
        await db_session.commit()

        assert await fail_interrupted_setups(db_session) == ["platform"]

        await db_session.refresh(stuck)
        await db_session.refresh(done)
        assert stuck.status == "setup_failed"
        assert stuck.error_message == INTERRUPTED
        assert stuck.setup_log["install_system_deps"]["status"] == "failed"
        assert stuck.setup_log["install_system_deps"]["error"] == INTERRUPTED
        assert stuck.setup_log["ssh_test"]["status"] == "skipped"
        assert stuck.setup_log["create_worker_user"]["status"] == "pending"
        assert done.status == "online"
        assert done.setup_log["ssh_test"]["status"] == "running"

    async def test_nothing_to_do(self, db_session):
        assert await fail_interrupted_setups(db_session) == []

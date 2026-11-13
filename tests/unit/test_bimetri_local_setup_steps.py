# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: which setup steps a local platform skips, and the dash-safe useradd line."""

import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.services.workspace.setup_service import local_skip_steps
from backend.services.workspace.worker_user_service import WorkerUserService

USER_STEPS = {"create_worker_user", "create_workspace_dir", "install_agents", "sync_agents"}


def _server(server_type, worker_user=None):
    return SimpleNamespace(server_type=server_type, worker_user=worker_user)


class TestLocalSkipSteps:
    def test_remote_server_runs_every_step(self):
        assert local_skip_steps(_server("remote")) == set()

    def test_root_platform_skips_ssh_and_worker_user_steps(self):
        assert local_skip_steps(_server("local")) == {"ssh_test", "generate_ssh_key"} | USER_STEPS

    def test_platform_with_run_as_user_still_sets_that_user_up(self):
        assert local_skip_steps(_server("local", "coder")) == {"ssh_test", "generate_ssh_key"}


class TestTestsNeverStartRealSetup:
    async def test_creating_a_server_hits_the_conftest_guard(self, client, _no_real_server_setup):
        resp = await client.post(
            "/api/workspace-servers", json={"name": "guard-srv", "hostname": "10.0.0.9"}
        )
        assert resp.status_code == 201
        _no_real_server_setup.assert_called_once()


class TestCreateUserCommand:
    async def test_existence_check_works_under_dash(self):
        ssh = AsyncMock()
        ssh.run_command = AsyncMock(return_value=("", "boom", 1))
        await WorkerUserService(ssh).setup("nobody-here-xyz")
        cmd = ssh.run_command.await_args_list[0].args[0]
        assert "&>" not in cmd
        # Under /bin/sh the guard must fail for a missing user so useradd would run.
        guard = cmd.split(" || ")[0]
        assert subprocess.run(["sh", "-c", guard]).returncode != 0

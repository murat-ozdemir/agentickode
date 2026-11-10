# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 2): merge-time code graph refresh on the idle workers."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.services import bimetri_graph
from tests.unit.test_workspace_selector import (  # noqa: F401 - pytest fixtures
    make_persisted_task_run,
    make_project_config,
    make_workspace_server,
)


class TestRefreshCommand:
    def test_syncs_and_updates_as_the_worker_user_under_the_lock(self):
        cmd = bimetri_graph.refresh_command("/workspaces/o/my repo", "master", "coder")
        assert cmd.startswith("cd '/workspaces/o/my repo' && test -d .git && runuser -l coder")
        assert "flock -n .git/bimetri-graph.lock sh -c" in cmd
        assert "git reset -q --hard origin/master" in cmd
        assert "chown -R coder:coder ." in cmd
        assert "update graphify" in cmd

    def test_without_a_worker_user_runs_as_the_ssh_user(self):
        cmd = bimetri_graph.refresh_command("/w", "main", None)
        assert "runuser" not in cmd
        assert "chown" not in cmd
        assert "/usr/bin/python3 ~/.local/share/bimetri-graph/agent_graph.py update" in cmd


class TestWaitForRefresh:
    async def test_waits_on_the_clone_lock(self):
        ssh = AsyncMock()
        await bimetri_graph.wait_for_refresh(ssh, "/w")
        assert "flock -w 600 .git/bimetri-graph.lock true" in ssh.run_command.call_args.args[0]

    async def test_errors_do_not_stop_the_run(self):
        ssh = AsyncMock()
        ssh.run_command.side_effect = OSError("ssh down")
        await bimetri_graph.wait_for_refresh(ssh, "/w")


class TestScheduleRefresh:
    @pytest.fixture()
    def calls(self, monkeypatch):
        calls = []

        async def fake_refresh(ssh, name, workspace, branch, user):
            calls.append((name, workspace, branch, user))

        monkeypatch.setattr(bimetri_graph, "refresh", fake_refresh)
        monkeypatch.setattr(bimetri_graph, "executor_for_server", lambda server: object())
        return calls

    async def test_refreshes_idle_workers_only(
        self,
        db_session,
        calls,
        make_workspace_server,  # noqa: F811
        make_project_config,  # noqa: F811
        make_persisted_task_run,  # noqa: F811
    ):
        idle = await make_workspace_server(worker_user="coder")
        busy = await make_workspace_server()
        await make_workspace_server()  # not linked to the project
        project = await make_project_config(workspace_server_ids=[idle.id, busy.id])
        await make_persisted_task_run(
            project_id=project.project_id, workspace_server_id=busy.id, status="running"
        )

        started = await bimetri_graph.schedule_refresh(db_session, project)
        await asyncio.gather(*bimetri_graph._tasks)

        assert started == [idle.name]
        workspace = f"/workspaces/{project.repo_owner}/{project.repo_name}"
        assert calls == [(idle.name, workspace, "main", "coder")]

    async def test_worker_user_equal_to_the_ssh_user_is_not_dropped_to(
        self,
        db_session,
        calls,
        make_workspace_server,  # noqa: F811
        make_project_config,  # noqa: F811
    ):
        server = await make_workspace_server(worker_user="root")
        project = await make_project_config(workspace_server_ids=[server.id])
        await bimetri_graph.schedule_refresh(db_session, project)
        await asyncio.gather(*bimetri_graph._tasks)
        assert calls[0][3] is None

    @pytest.mark.parametrize(
        "overrides",
        [{"workspace_config": {"workspace_type": "new"}}, {"local_path": "/home/op/repo"}],
    )
    async def test_skips_projects_without_a_shared_clone(
        self,
        db_session,
        calls,
        overrides,
        make_workspace_server,  # noqa: F811
        make_project_config,  # noqa: F811
    ):
        server = await make_workspace_server()
        project = await make_project_config(workspace_server_ids=[server.id], **overrides)
        assert await bimetri_graph.schedule_refresh(db_session, project) == []
        assert calls == []

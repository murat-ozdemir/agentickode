# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a restarted run gets its path and server the way a new run would."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.api.runs_actions import reset_run_for_restart
from backend.models import ProjectConfig


def _run(**kw):
    base = dict(
        project_id="backend",
        task_id="85",
        repo_name="platform-backend",
        workspace_path="/workspaces/platform-backend",
        workspace_server_id=1,
        status="failed",
        error_message="Ajan CLI hata koduyla bitti (1)",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _project(**kw):
    return ProjectConfig(
        project_id="backend", repo_owner="Bienport-IoT", repo_name="platform-backend", **kw
    )


async def test_owner_path_and_server_reselected():
    db = SimpleNamespace(get=AsyncMock(return_value=_project()))
    run = _run()
    await reset_run_for_restart(run, db)
    assert run.workspace_path == "/workspaces/Bienport-IoT/platform-backend"
    assert run.workspace_server_id is None
    assert run.status == "pending"
    assert run.error_message is None


async def test_project_path_wins():
    db = SimpleNamespace(get=AsyncMock(return_value=_project(workspace_path="/srv/pb")))
    run = _run()
    await reset_run_for_restart(run, db)
    assert run.workspace_path == "/srv/pb"


async def test_cluster_workspace_uses_task_id():
    project = _project(workspace_config={"workspace_type": "cluster"})
    db = SimpleNamespace(get=AsyncMock(return_value=project))
    run = _run()
    await reset_run_for_restart(run, db)
    assert run.workspace_path == "/workspaces/85"


async def test_missing_project_falls_back_to_repo_name():
    db = SimpleNamespace(get=AsyncMock(return_value=None))
    run = _run()
    await reset_run_for_restart(run, db)
    assert run.workspace_path == "platform-backend"
    assert run.workspace_server_id is None

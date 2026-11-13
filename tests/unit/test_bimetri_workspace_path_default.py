# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: readiness checks look where runs clone the project."""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.run_factory import default_workspace_path
from backend.services.workspace.readiness_service import ValidationReport


def _project(workspace_path=None):
    return SimpleNamespace(
        project_id="inventory-mgm",
        repo_owner="Inventory",
        repo_name="inventory-mgm",
        workspace_path=workspace_path,
        workspace_config={},
        workspace_servers=[SimpleNamespace(workspace_server_id=3)],
    )


def _server():
    return SimpleNamespace(
        id=3, name="worker-1", workspace_root="/home/coder/workspaces", worker_user="coder"
    )


class TestDefaultWorkspacePath:
    def test_unset_path_follows_gitea_layout(self):
        assert default_workspace_path(_project()) == "/workspaces/Inventory/inventory-mgm"

    def test_set_path_wins(self):
        assert default_workspace_path(_project("/srv/inv")) == "/srv/inv"


class TestValidateUsesRunPath:
    async def test_validate_checks_the_run_clone(self, client):
        with (
            patch("backend.api.servers.readiness.WorkspaceServerRepository") as srv_cls,
            patch("backend.api.servers.readiness.ProjectConfigRepository") as proj_cls,
            patch("backend.api.servers.readiness.WorkspaceReadinessRepository") as repo_cls,
            patch("backend.api.servers.readiness.WorkspaceReadinessService") as svc_cls,
            patch("backend.api.servers.readiness.executor_for_server"),
        ):
            srv_cls.return_value.get_by_id = AsyncMock(return_value=_server())
            proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
            svc_cls.return_value.validate = AsyncMock(
                return_value=ValidationReport(passed=False, summary="x", checks=[])
            )
            repo_cls.return_value.upsert = AsyncMock(side_effect=RuntimeError("stop"))

            with contextlib.suppress(RuntimeError):
                await client.post("/api/workspace-servers/3/projects/inventory-mgm/validate")

        path = svc_cls.return_value.validate.await_args.args[0]
        assert path == "/workspaces/Inventory/inventory-mgm"


class TestProjectReadinessUsesRunPath:
    async def test_clone_check_looks_at_the_run_clone(self, client):
        ssh = MagicMock(run_command=AsyncMock(return_value=("exists", "", 0)))
        with (
            patch("backend.api.projects.ProjectConfigRepository") as proj_cls,
            patch("backend.api.projects.WorkspaceServerRepository") as srv_cls,
            patch("backend.api.projects.executor_for_server", return_value=ssh),
        ):
            proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
            srv_cls.return_value.get_by_id = AsyncMock(return_value=_server())
            resp = await client.get("/api/projects/inventory-mgm/workspace-readiness")

        assert resp.status_code == 200
        assert (
            "test -d /workspaces/Inventory/inventory-mgm/.git"
            in (ssh.run_command.await_args.args[0])
        )

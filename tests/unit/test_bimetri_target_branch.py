# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: runs of a project work on its shared project branch."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from backend.api import _pr_webhook_helpers as helpers
from backend.models import ProjectConfig, TaskRun
from backend.services._bimetri_target_branch import (
    close_issues,
    merged_off_default,
    run_base_branch,
    target_branch,
)
from backend.services.git.gitea import GiteaProvider


@pytest.mark.parametrize(
    "body",
    [
        "Hedef dal: prj/TCW242-INTG",
        "**Hedef dal:** `prj/TCW242-INTG`",
        "**Hedef dal**: prj/TCW242-INTG.",
        "<strong>Hedef dal:</strong> prj/TCW242-INTG",
        "## Kapsam\nbir sey\n\n- hedef DAL: prj/TCW242-INTG\n",
        "Target branch: prj/TCW242-INTG",
    ],
)
def test_target_branch_reads_the_line(body):
    assert target_branch(body) == "prj/TCW242-INTG"


@pytest.mark.parametrize(
    "body", ["", None, "Hedef dal:", "Hedef dal: ../main", "Hedef dal: -x", "dal: prj/X"]
)
def test_target_branch_ignores_missing_or_invalid(body):
    assert target_branch(body) is None


def test_run_base_branch_prefers_pr_base_then_issue_line():
    body = "Hedef dal: prj/A"
    assert run_base_branch("main", body, {"pr_base_branch": "prj/B"}) == "prj/B"
    assert run_base_branch("main", body, {"pr_number": 4}) == "main"
    assert run_base_branch("main", body, {}) == "prj/A"
    assert run_base_branch("main", "no line", None) == "main"


def test_merged_off_default():
    assert merged_off_default({"base": {"ref": "prj/A"}}, "main")
    assert not merged_off_default({"base": {"ref": "main"}}, "main")
    assert not merged_off_default({}, "main")


async def test_close_issues_patches_each_issue():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.read()))
        return httpx.Response(500 if request.url.path.endswith("/9") else 201, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GiteaProvider(client, base_url="https://gitea.test", token="tok")
        assert await close_issues(provider, "org/r", [7, 9]) == [7]
    assert calls[0][:2] == ("PATCH", "/api/v1/repos/org/r/issues/7")
    assert b'"state":"closed"' in calls[0][2].replace(b" ", b"")


@pytest.fixture()
async def gitea_project(db_session):
    p = ProjectConfig(
        project_id="gitea-proj",
        project_slug="gitea-proj",
        repo_owner="myorg",
        repo_name="myrepo",
        default_branch="main",
        task_source="gitea",
        git_provider="gitea",
        workspace_path="/workspaces/myrepo",
    )
    db_session.add(p)
    await db_session.commit()
    return p


async def _issue_run(client, db_session, body: str) -> TaskRun:
    payload = {
        "action": "opened",
        "issue": {"number": 7, "title": "Add field", "body": body, "labels": [{"name": "ai-task"}]},
        "repository": {"full_name": "myorg/myrepo"},
    }
    assert (await client.post("/api/webhooks/gitea", json=payload)).json()["status"] == "accepted"
    return (await db_session.execute(select(TaskRun))).scalar_one()


async def test_issue_with_target_line_runs_on_project_branch(
    client: AsyncClient, gitea_project, db_session
):
    run = await _issue_run(client, db_session, "**Hedef dal:** `prj/TCW242-INTG`\n\nKapsam")
    assert run.default_branch == "prj/TCW242-INTG"


async def test_issue_without_target_line_runs_on_default_branch(
    client: AsyncClient, gitea_project, db_session
):
    run = await _issue_run(client, db_session, "Kapsam")
    assert run.default_branch == "main"


def test_pr_review_run_uses_pr_base_branch(gitea_project):
    run = helpers.build_pr_review_run(
        gitea_project,
        task_source="gitea",
        pr_number=3,
        pr_title="t",
        pr_body="Hedef dal: prj/X",
        pr_head_branch="feature/7-x",
        pr_url="",
        repo_full_name="myorg/myrepo",
        labels=["ai-review"],
        pr_base_branch="prj/Y",
    )
    assert run.default_branch == "prj/Y"


async def _merge(base: str):
    project = SimpleNamespace(
        project_id="p",
        repo_owner="org",
        repo_name="repo",
        workspace_server_id=None,
        default_branch="main",
    )
    repo = MagicMock(get_by_git_repo=AsyncMock(return_value=project))
    gp = MagicMock(set_status_label=AsyncMock())
    pr = {"number": 12, "body": "Closes #7", "base": {"ref": base}}
    body = {"pull_request": pr, "repository": {"full_name": "org/repo", "default_branch": "main"}}
    with (
        patch("backend.worker.phases._helpers.get_project_token", AsyncMock(return_value="t")),
        patch("backend.services.git.get_git_provider", return_value=gp),
        patch("backend.worker.flow._bimetri_ozellik.arka_planda_yaz"),
        patch("backend.worker.flow._bimetri_proposals.schedule_proposals"),
        patch("backend.services.bimetri_graph.schedule_refresh", AsyncMock()) as refresh,
        patch(
            "backend.services._bimetri_target_branch.close_issues", AsyncMock(return_value=[7])
        ) as close,
    ):
        result = await helpers._bimetri_pr_merged(body, MagicMock(), repo)
    return result, gp, refresh, close


async def test_merge_into_project_branch_closes_issue_and_skips_graph():
    result, gp, refresh, close = await _merge("prj/A")
    assert result["completed"] == [7, 12]
    assert result["closed"] == [7]
    assert close.await_args.args[1:] == ("org/repo", [7])
    refresh.assert_not_awaited()


async def test_merge_into_default_branch_leaves_closing_to_gitea():
    result, gp, refresh, close = await _merge("main")
    assert "closed" not in result
    close.assert_not_awaited()
    refresh.assert_awaited_once()

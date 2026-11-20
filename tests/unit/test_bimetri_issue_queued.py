# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: status/open goes on the issue before its run is saved.

The worker takes a run as soon as it is committed and sets status/in-progress;
an ``open`` set after the commit wiped it (exclusive status labels, issue #9).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from backend.api import _bimetri_issue_label
from backend.models import ProjectConfig, TaskRun


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


def _payload():
    return {
        "action": "opened",
        "issue": {
            "number": 9,
            "title": "Sürüm notları",
            "body": "",
            "labels": [{"name": "ai-task"}],
        },
        "repository": {"full_name": "myorg/myrepo"},
    }


async def test_status_open_is_set_before_the_run_is_saved(client: AsyncClient, gitea_project):
    runs_seen = []

    async def fake_mark(db, project, repo_full_name, number):
        runs_seen.append(await db.scalar(select(func.count()).select_from(TaskRun)))

    with patch.object(_bimetri_issue_label, "mark_issue_queued", new=fake_mark):
        resp = await client.post("/api/webhooks/gitea", json=_payload())

    assert resp.json()["status"] == "accepted"
    assert runs_seen == [0]


async def test_open_label_and_assignee_go_to_the_issue(client: AsyncClient, gitea_project):
    provider = MagicMock(set_status_label=AsyncMock(), assign_self=AsyncMock())
    with patch("backend.services.git.get_git_provider", return_value=provider):
        resp = await client.post("/api/webhooks/gitea", json=_payload())

    assert resp.json()["status"] == "accepted"
    provider.set_status_label.assert_awaited_once_with("myorg/myrepo", 9, "status/open")
    provider.assign_self.assert_awaited_once_with("myorg/myrepo", 9)


async def test_label_failure_still_creates_the_run(client: AsyncClient, gitea_project):
    provider = MagicMock(set_status_label=AsyncMock(side_effect=RuntimeError("gitea down")))
    with patch("backend.services.git.get_git_provider", return_value=provider):
        resp = await client.post("/api/webhooks/gitea", json=_payload())

    assert resp.json()["status"] == "accepted"
    assert resp.json()["run_id"] > 0

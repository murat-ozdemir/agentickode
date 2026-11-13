# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: ai-task added later (Gitea label_updated) starts exactly one run."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from backend.api._bimetri_issue_label import trigger_action
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


def _payload(action: str, labels: list[str], number: int = 7) -> dict:
    return {
        "action": action,
        "issue": {
            "number": number,
            "title": "Reject empty serial",
            "body": "body",
            "labels": [{"name": n} for n in labels],
        },
        "repository": {"full_name": "myorg/myrepo"},
    }


async def _run_count(db_session, task_id: str = "7") -> int:
    q = select(func.count()).select_from(TaskRun).where(TaskRun.task_id == task_id)
    return (await db_session.execute(q)).scalar_one()


def test_trigger_action_maps_label_updated_to_labeled():
    assert trigger_action("label_updated") == "labeled"
    assert trigger_action("opened") == "opened"


class TestLabelUpdated:
    async def test_ai_task_added_later_starts_a_run(
        self, client: AsyncClient, gitea_project, db_session
    ):
        resp = await client.post(
            "/api/webhooks/gitea", json=_payload("label_updated", ["branch/bug", "ai-task"])
        )
        assert resp.json()["status"] == "accepted"
        assert await _run_count(db_session) == 1

    async def test_label_change_without_ai_task_is_ignored(
        self, client: AsyncClient, gitea_project, db_session
    ):
        resp = await client.post(
            "/api/webhooks/gitea", json=_payload("label_updated", ["branch/bug"])
        )
        assert resp.json() == {"status": "ignored", "reason": "not_ai_task"}
        assert await _run_count(db_session) == 0

    async def test_opened_then_label_updated_creates_one_run(
        self, client: AsyncClient, gitea_project, db_session
    ):
        first = await client.post("/api/webhooks/gitea", json=_payload("opened", ["ai-task"]))
        second = await client.post(
            "/api/webhooks/gitea", json=_payload("label_updated", ["ai-task"])
        )
        assert first.json()["status"] == "accepted"
        assert second.json() == {"status": "ignored", "reason": "run_exists"}
        assert await _run_count(db_session) == 1

    async def test_status_label_change_does_not_start_another_run(
        self, client: AsyncClient, gitea_project, db_session
    ):
        await client.post("/api/webhooks/gitea", json=_payload("label_updated", ["ai-task"]))
        resp = await client.post(
            "/api/webhooks/gitea",
            json=_payload("label_updated", ["ai-task", "status/in-progress"]),
        )
        assert resp.json()["reason"] == "run_exists"
        assert await _run_count(db_session) == 1

    async def test_other_issue_still_gets_its_own_run(
        self, client: AsyncClient, gitea_project, db_session
    ):
        await client.post("/api/webhooks/gitea", json=_payload("opened", ["ai-task"], number=7))
        resp = await client.post(
            "/api/webhooks/gitea", json=_payload("label_updated", ["ai-task"], number=8)
        )
        assert resp.json()["status"] == "accepted"
        assert await _run_count(db_session, "8") == 1

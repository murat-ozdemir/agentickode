# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a final ci-kapisi status writes CI time; only a red one asks for a fix."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.config import settings

URL = "/api/webhooks/gitea-ci"


def _body(state: str, context: str = "ci-kapisi") -> dict:
    return {
        "context": context,
        "state": state,
        "sha": "abc12345ff",
        "updated_at": "2026-11-20T13:25:00+03:00",
        "repository": {"full_name": "org/repo"},
    }


@contextmanager
def _mocks():
    repo_cls = "backend.repositories.project_config_repo.ProjectConfigRepository.get_by_git_repo"
    with (
        patch.object(settings, "gitea_webhook_secret", ""),
        patch(repo_cls, AsyncMock(return_value=SimpleNamespace(project_id="p"))),
        patch("backend.api._bimetri_push.proje_saglayici", AsyncMock(return_value="gp")),
        patch(
            "backend.worker.phases._bimetri_time_tracking.record_ci_time",
            AsyncMock(return_value="#5: CI time written"),
        ) as ci_time,
        patch(
            "backend.worker.phases._bimetri_ci_kirmizi.ci_kirmizi",
            AsyncMock(return_value="ok"),
        ) as red,
    ):
        yield ci_time, red


class TestCiTimeWebhook:
    async def test_green_gate_writes_time_without_fix_round(self, client):
        with _mocks() as (ci_time, red):
            r = await client.post(URL, json=_body("success"))
        assert r.json() == {"status": "accepted", "reason": "ci_time"}
        end = ci_time.await_args.args[3]
        assert end == datetime(2026, 11, 20, 10, 25, tzinfo=UTC)
        red.assert_not_awaited()

    async def test_red_gate_writes_time_and_asks_for_fix(self, client):
        with _mocks() as (ci_time, red):
            r = await client.post(URL, json=_body("failure"))
        assert r.json()["reason"] == "ok"
        ci_time.assert_awaited_once()
        red.assert_awaited_once()

    async def test_time_error_does_not_block_fix_round(self, client):
        with _mocks() as (ci_time, red):
            ci_time.side_effect = RuntimeError("gitea down")
            await client.post(URL, json=_body("error"))
        red.assert_awaited_once()

    async def test_pending_or_other_context_is_ignored(self, client):
        with _mocks() as (ci_time, _red):
            assert (await client.post(URL, json=_body("pending"))).json()["status"] == "ignored"
            assert (await client.post(URL, json=_body("success", "lint"))).json()[
                "status"
            ] == "ignored"
        ci_time.assert_not_awaited()

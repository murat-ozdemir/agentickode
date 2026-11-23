# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 7): the `devam <yanıt>` answer goes to the notebook."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.config import settings
from backend.models import ProjectConfig
from tests.unit.bimetri_sahte import SahteGitea

URL = "/api/webhooks/gitea-pr-comment"
pytestmark = pytest.mark.usefixtures("seed_proj1")


def _body(text: str) -> dict:
    return {
        "action": "created",
        "is_pull": True,
        "issue": {"number": 5, "pull_request": {}},
        "comment": {"id": 70, "body": text, "user": {"login": "mozdemir"}, "created_at": "t"},
        "repository": {"full_name": "org/repo"},
    }


async def _post(client, db_session, text: str) -> AsyncMock:
    gp = SahteGitea()
    gp.pr[5] = {
        "state": "open",
        "title": "PR",
        "html_url": "https://gitea.test/org/repo/pulls/5",
        "head": {"ref": "ai/x", "repo": {"full_name": "org/repo"}},
    }
    project = await db_session.get(ProjectConfig, "proj-1")
    komut = "backend.api._bimetri_komut"
    with (
        patch.object(settings, "gitea_webhook_secret", ""),
        patch(
            "backend.repositories.project_config_repo.ProjectConfigRepository.get_by_git_repo",
            AsyncMock(return_value=project),
        ),
        patch("backend.api._bimetri_push.proje_saglayici", AsyncMock(return_value=gp)),
        patch(f"{komut}.bot_yorumu_mu", AsyncMock(return_value=False)),
        patch(f"{komut}.yazma_yetkisi", AsyncMock(return_value=True)),
        patch(f"{komut}.devam_isareti", AsyncMock()),
        patch(
            "backend.worker.phases._bimetri_notebook_record.record_answer", AsyncMock()
        ) as answer,
    ):
        r = await client.post(URL, json=_body(text))
    assert r.json()["status"] == "accepted"
    return answer


async def test_devam_with_answer_is_recorded(client, db_session):
    answer = await _post(client, db_session, "@agentickode devam 409 dön")

    assert answer.await_args.args[1:] == ("proj-1", 5, "mozdemir", "409 dön")


async def test_plain_devam_records_nothing(client, db_session):
    answer = await _post(client, db_session, "@agentickode devam")

    answer.assert_not_awaited()

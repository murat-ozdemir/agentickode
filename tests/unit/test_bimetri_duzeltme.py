# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: PR yorumuyla duzeltme kosusunun finalization adimi."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.worker.phases import finalization
from tests.unit.bimetri_sahte import SahteGit

_META = {
    "pr_head_branch": "feature/x",
    "review_mode": "fix",
    "pr_number": 5,
    "pr_url": "https://gitea.test/org/repo/pulls/5",
}


class TestDuzeltmeKosusu:
    @pytest.fixture(autouse=True)
    async def _project_parent(self, db_session):
        from backend.models import ProjectConfig

        db_session.add(
            ProjectConfig(project_id="proj-1", project_slug="x", repo_owner="o", repo_name="r")
        )
        await db_session.commit()

    async def _calistir(self, db_session, make_task_run, mock_services, git: SahteGit):
        run = make_task_run(
            pr_url=None,
            task_source_meta=dict(_META),
            coding_results={"agent": "agent/codex@agent-2", "model": "gpt-6-luna"},
        )
        db_session.add(run)
        await db_session.commit()
        gp = AsyncMock()
        push = AsyncMock()
        with (
            patch(
                "backend.worker.phases.finalization.get_ssh_for_run",
                new=AsyncMock(return_value=AsyncMock()),
            ),
            patch("backend.worker.phases.finalization.RemoteSandbox") as mock_sb_cls,
            patch(
                "backend.worker.phases.finalization.broadcaster",
                new=MagicMock(log=AsyncMock(), event=AsyncMock()),
            ),
            patch("backend.worker.phases.finalization._push_to_pr_branch", new=push),
            patch("backend.worker.phases.finalization.RemoteGitOps", return_value=git),
            patch("backend.worker.phases.finalization.get_project_token", new=AsyncMock()),
            patch("backend.worker.phases.finalization.get_git_provider", return_value=gp),
        ):
            mock_sb_cls.return_value.stop_sandbox = AsyncMock()
            await finalization.run(run, db_session, mock_services)
        return gp, push

    async def test_pushes_and_restarts_test_chain(self, db_session, make_task_run, mock_services):
        gp, push = await self._calistir(db_session, make_task_run, mock_services, SahteGit())
        push.assert_awaited_once()
        gp.add_label.assert_awaited_once_with("org/repo", 5, "ai-test")
        govde = gp.post_pr_comment.await_args.args[2]
        assert govde.startswith("## Düzeltme push edildi (1 commit)")
        alt = govde.replace("​", "").rsplit("\n", 1)[-1]
        assert alt.startswith("Ajan: agent/codex@agent-2 · Model: gpt-6-luna · Koşu: [#")

    async def test_no_new_commit_fails_without_push(self, db_session, make_task_run, mock_services):
        with pytest.raises(RuntimeError, match="degisiklik birakmadi"):
            await self._calistir(db_session, make_task_run, mock_services, SahteGit(ahead="0"))

    async def test_touching_tests_stops_chain(self, db_session, make_task_run, mock_services):
        git = SahteGit(diff="src/main/A.java\nmod/src/test/ATest.java")
        with pytest.raises(RuntimeError, match="test dosyalarina dokundu"):
            await self._calistir(db_session, make_task_run, mock_services, git)

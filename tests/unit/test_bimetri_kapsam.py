# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: inceleme/duzeltme kosularina bagli issue ve kapsam kurallari."""

from unittest.mock import AsyncMock, patch

from backend.worker.flow import _bimetri_kapsam as kapsam

_ISSUE = {"title": "Seri numarası doğrulayıcı", "body": "Mevcut koda bağlama."}


def _run(make_task_run, **kw):
    kw.setdefault("git_provider", "gitea")
    return make_task_run(**kw)


class TestKapsamEki:
    async def test_review_gets_issue_from_closes_line(self, make_task_run):
        run = _run(make_task_run, description="Closes #32", task_source_meta={"pr_number": 33})
        oku = AsyncMock(return_value=_ISSUE)
        with patch.object(kapsam, "_issue_oku", new=oku):
            ek = await kapsam.kapsam_eki(run, None, "inceleme")
        assert oku.await_args.args[2] == 32
        assert "## Bağlı issue #32: Seri numarası doğrulayıcı" in ek
        assert "Mevcut koda bağlama." in ek
        assert "### Kapsam dışı" in ek

    async def test_fix_prefers_meta_issue_number(self, make_task_run):
        run = _run(make_task_run, description="Closes #1", task_source_meta={"issue_number": 7})
        oku = AsyncMock(return_value=_ISSUE)
        with patch.object(kapsam, "_issue_oku", new=oku):
            ek = await kapsam.kapsam_eki(run, None, "duzeltme")
        assert oku.await_args.args[2] == 7
        assert "doğrulanamadı" in ek
        assert "Kapsam dışı" in ek

    async def test_fetch_failure_still_adds_rules(self, make_task_run):
        run = _run(make_task_run, task_source_meta={"issue_number": 7})
        with patch.object(kapsam, "_issue_oku", new=AsyncMock(side_effect=RuntimeError("x"))):
            ek = await kapsam.kapsam_eki(run, None, "inceleme")
        assert "Bağlı issue" not in ek
        assert ek.startswith("\n## Kapsam kuralları")

    async def test_no_issue_skips_fetch(self, make_task_run):
        run = _run(make_task_run, description="", task_source_meta={})
        oku = AsyncMock()
        with patch.object(kapsam, "_issue_oku", new=oku):
            await kapsam.kapsam_eki(run, None, "duzeltme")
        oku.assert_not_awaited()

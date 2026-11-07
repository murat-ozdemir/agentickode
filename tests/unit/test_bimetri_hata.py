# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: kullanim limitinin taninmasi ve basarisiz kosu yorumu."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.worker.phases import _bimetri_hata as hata
from backend.worker.phases._bimetri_hata import hata_yorumu, limit_nedeni, yorum_gerekli
from tests.unit.bimetri_sahte import SahteGitea


class TestLimitNedeni:
    def test_claude_new_format(self):
        rd = {"output": "You've hit your limit · resets 3pm (Europe/Istanbul)", "exit_code": 1}
        assert limit_nedeni("claude", rd) == (
            "Kullanım limiti doldu (claude, sıfırlanma: 3pm (Europe/Istanbul))"
        )

    def test_claude_epoch_format(self):
        rd = {"output": {"result": "Claude AI usage limit reached|1762430400"}}
        assert (
            limit_nedeni("claude", rd) == "Kullanım limiti doldu (claude, sıfırlanma: 06.11 15:00)"
        )

    def test_codex_format_in_stderr(self):
        rd = {"output": "", "stderr": "You've hit your usage limit. Try again at 3:05 PM."}
        assert limit_nedeni("codex", rd) == "Kullanım limiti doldu (codex, sıfırlanma: 3:05 PM)"

    def test_other_errors_are_not_limit(self):
        assert limit_nedeni("claude", {"output": "compilation failed", "stderr": ""}) is None
        assert limit_nedeni("claude", None) is None


class TestHataYorumu:
    def test_fix_and_test_failures_already_comment(self):
        assert not yorum_gerekli("Duzeltme kosusu: testler kaldi")
        assert not yorum_gerekli("Test kosusu: 2 hata")
        assert yorum_gerekli("Ajan CLI hata koduyla bitti (1)")

    def test_limit_comment_explains_restart(self):
        govde = hata_yorumu(9, "https://crew.test/runs/9", "Kullanım limiti doldu (claude)")
        assert "[#9](https://crew.test/runs/9)" in govde
        assert "Limit sıfırlanınca" in govde

    def test_mentions_are_neutralised(self):
        govde = hata_yorumu(9, "u", "@agentickode boom")
        assert "@agentickode" not in govde
        assert govde.count("@​agentickode") == 2


class TestHataBildir:
    def _run(self, **meta):
        return SimpleNamespace(
            id=9,
            git_provider="gitea",
            repo_owner="org",
            repo_name="repo",
            pr_url=meta.pop("pr_url", None),
            task_source_meta=meta,
        )

    async def _bildir(self, run, metin: str) -> SahteGitea:
        gp = SahteGitea()
        with (
            patch("backend.services.git.get_git_provider", return_value=gp),
            patch("backend.worker.phases._helpers.get_project_token", AsyncMock(return_value="t")),
        ):
            await hata.hata_bildir(run, None, metin)
        return gp

    async def test_prefers_pr_over_issue(self):
        gp = await self._bildir(self._run(issue_number=3, pr_url="https://g/o/r/pulls/12"), "x")
        assert list(gp.yorum) == [12]

    async def test_falls_back_to_issue(self):
        gp = await self._bildir(self._run(issue_number=3), "x")
        assert list(gp.yorum) == [3]

    async def test_skips_errors_that_comment_themselves(self):
        gp = await self._bildir(self._run(issue_number=3), "Test kosusu: kaldi")
        assert gp.yorum == {}

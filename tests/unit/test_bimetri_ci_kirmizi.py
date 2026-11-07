# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: kirmizi ci-kapisi botun PR'inda duzeltme turu yorumu acar."""

from backend.worker.phases._bimetri_ci_kirmizi import CI_ISARET, ci_kirmizi, log_ozeti
from backend.worker.phases._bimetri_oto import OTO_ISARET
from tests.unit.bimetri_sahte import SahteGitea

RP = "org/repo"
SHA = "abc12345ff"
LOG = (
    "2026-11-07T10:00:00.1Z [INFO] Building\n"
    "2026-11-07T10:00:01.2Z \x1b[31m[ERROR] Tests run: 3, Failures: 1, Errors: 0\x1b[0m\n"
    "2026-11-07T10:00:02.3Z [ERROR] @user AuthTest.login\n"
)


def _gitea(kullanici: str = "agentickode") -> SahteGitea:
    gp = SahteGitea()
    gp.pr[5] = {"number": 5, "state": "open", "user": {"login": kullanici}, "head": {"sha": SHA}}
    gp.yanitlar[f"/repos/{RP}/pulls"] = (200, [gp.pr[5]])
    gp.yanitlar[f"/repos/{RP}/actions/runs"] = (
        200,
        {"workflow_runs": [{"id": 7, "path": "dev.yml@refs/heads/feat/x"}]},
    )
    gp.yanitlar[f"/repos/{RP}/actions/runs/7/jobs"] = (
        200,
        {"jobs": [{"id": 70, "conclusion": "success"}, {"id": 71, "conclusion": "failure"}]},
    )
    gp.yanitlar[f"/repos/{RP}/actions/jobs/71/logs"] = (200, LOG)
    return gp


class TestLogOzeti:
    def test_keeps_error_lines_without_timestamp_or_colour(self):
        ozet = log_ozeti(LOG)
        assert ozet.splitlines()[0] == "[ERROR] Tests run: 3, Failures: 1, Errors: 0"
        assert "[INFO]" not in ozet

    def test_falls_back_to_last_lines(self):
        assert log_ozeti("a\nb") == "a\nb"


class TestCiKirmizi:
    async def test_bot_pr_gets_fix_comment_with_log(self):
        gp = _gitea()
        sonuc = await ci_kirmizi(gp, RP, SHA, "https://gitea.test/kosu/7")
        govde = gp.yorum[5][0]
        assert "PR #5" in sonuc
        assert govde.startswith("@agentickode") and OTO_ISARET in govde
        assert CI_ISARET.format(sha=SHA) in govde
        assert "Failures: 1" in govde and "@​user" in govde
        assert "https://gitea.test/kosu/7" in govde

    async def test_same_sha_is_written_once(self):
        gp = _gitea()
        await ci_kirmizi(gp, RP, SHA)
        assert await ci_kirmizi(gp, RP, SHA) == "bu commit icin zaten yazildi"
        assert len(gp.yorum[5]) == 1

    async def test_human_pr_is_ignored(self):
        gp = _gitea("murat")
        assert await ci_kirmizi(gp, RP, SHA) == "otomatik tur yok"
        assert 5 not in gp.yorum

    async def test_no_open_pr(self):
        gp = _gitea()
        assert await ci_kirmizi(gp, RP, "baska") == "acik PR yok"

    async def test_unreadable_log_still_comments(self):
        gp = _gitea()
        del gp.yanitlar[f"/repos/{RP}/actions/runs"]
        await ci_kirmizi(gp, RP, SHA)
        assert "Log okunamadı" in gp.yorum[5][0]

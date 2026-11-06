# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: CI kapisi (workflow_dispatch) ve belge-yalniz PR'da testin atlanmasi."""

from backend.worker.phases._bimetri_ci import CI_BAGLAM, ajan_testi_gerekli, belge_yalniz, ci_baslat
from tests.unit.bimetri_sahte import SahteGitea

RP = "org/repo"


def _gitea() -> SahteGitea:
    gp = SahteGitea()
    gp.pr[5] = {"head": {"sha": "abc12345ff", "ref": "feat/x"}}
    return gp


class TestBelgeYalniz:
    def test_docs_only(self):
        assert belge_yalniz(["README.md", "docs/kurulum.adoc", "LICENSE"])

    def test_code_or_unknown_is_not_docs_only(self):
        assert not belge_yalniz(["README.md", "src/main/java/A.java"])
        assert not belge_yalniz(["pom.xml"])
        assert not belge_yalniz([])


class TestTestGerekli:
    async def test_needs_mvnw_and_code_change(self):
        gp = _gitea()
        gp.dosya[5] = ["src/main/java/A.java"]
        assert await ajan_testi_gerekli(gp, RP, 5, True)
        assert not await ajan_testi_gerekli(gp, RP, 5, False)

    async def test_skipped_for_docs_only_pr(self):
        gp = _gitea()
        gp.dosya[5] = ["README.md"]
        assert not await ajan_testi_gerekli(gp, RP, 5, True)


class TestCiBaslat:
    async def test_dispatches_workflow_for_pr_head(self):
        gp = _gitea()
        sonuc = await ci_baslat(gp, RP, 5)
        assert "baslatildi" in sonuc
        assert gp.dispatch == [
            (
                f"/repos/{RP}/actions/workflows/dev.yml/dispatches",
                {"ref": "feat/x", "inputs": {"sha": "abc12345ff"}},
            )
        ]

    async def test_skips_when_commit_already_has_gate_status(self):
        gp = _gitea()
        gp.ci_durum["abc12345ff"] = [CI_BAGLAM]
        assert "zaten" in await ci_baslat(gp, RP, 5)
        assert gp.dispatch == []

    async def test_failed_dispatch_comments_on_pr(self):
        gp = _gitea()
        gp.dispatch_kodu = 404
        assert "baslatilamadi" in await ci_baslat(gp, RP, 5)
        assert "CI başlatılamadı" in gp.yorum[5][0]

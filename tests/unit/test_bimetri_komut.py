# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: yorum komutlari, yazma yetkisi, tekrar ve insan push'u."""

from types import SimpleNamespace

import pytest

from backend.api._bimetri_komut import (
    bot_yorumu_mu,
    inceleme_komutu,
    komut_ayikla,
    pr_komutu,
    yazma_yetkisi,
)
from backend.api._bimetri_push import push_karari
from backend.api._bimetri_tekrar import tekrar_baslat
from backend.worker.phases._bimetri_oto import OTO_ISARET
from tests.unit.bimetri_sahte import SahteGitea

RP = "org/repo"


class TestKomutAyikla:
    @pytest.mark.parametrize(
        ("govde", "beklenen"),
        [
            ("@agentickode review", ("review", "")),
            ("@agentickode incele lütfen", ("review", "lütfen")),
            ("@AgenticKode tekrar.", ("tekrar", "")),
            ("@agentickode devam null kontrolüne bak", ("devam", "null kontrolüne bak")),
            ("@agentickode testi düzelt", ("duzelt", "testi düzelt")),
            ("Bunu @agentickode retry", ("tekrar", "Bunu")),
        ],
    )
    def test_parses_first_word_after_mention(self, govde, beklenen):
        assert komut_ayikla(govde) == beklenen


class TestBotYorumu:
    async def test_bot_comment_without_auto_marker_is_ignored(self):
        gp = SahteGitea()
        assert await bot_yorumu_mu(gp, "agentickode", "`@agentickode devam <yönlendirme>`")
        assert not await bot_yorumu_mu(gp, "agentickode", f"@agentickode duzelt\n{OTO_ISARET}")
        assert not await bot_yorumu_mu(gp, "ali", "@agentickode devam")


class TestYazmaYetkisi:
    async def test_bot_is_allowed(self):
        assert await yazma_yetkisi(SahteGitea(), RP, "agentickode")

    async def test_permission_endpoint_decides_when_readable(self):
        gp = SahteGitea()
        gp.yanitlar[f"/repos/{RP}/collaborators/ali/permission"] = (200, {"permission": "read"})
        gp.yanitlar["/orgs/org/members/ali"] = (204, None)
        assert not await yazma_yetkisi(gp, RP, "ali")
        gp.yanitlar[f"/repos/{RP}/collaborators/ali/permission"] = (200, {"permission": "write"})
        assert await yazma_yetkisi(gp, RP, "ali")

    async def test_falls_back_to_collaborator_then_org_member(self):
        gp = SahteGitea()
        gp.yanitlar[f"/repos/{RP}/collaborators/ali/permission"] = (403, {})
        assert not await yazma_yetkisi(gp, RP, "ali")
        gp.yanitlar["/orgs/org/members/ali"] = (204, None)
        assert await yazma_yetkisi(gp, RP, "ali")


class TestIncelemeKomutu:
    async def test_on_hold_pr_moves_to_review_and_issue_gets_sticky_label(self):
        gp = SahteGitea()
        gp.etiket[5] = ["status/on-hold", "ai-reviewed"]
        await inceleme_komutu(gp, RP, 5, 1, list(gp.etiket[5]))
        assert gp.durum == {5: "status/review", 1: "status/review"}
        assert "ai-review" in gp.etiket[1]
        assert gp.etiket[5] == ["status/review", "ai-review"]


class TestPrKomutu:
    def test_retry_with_instruction_on_pr_becomes_fix_run(self):
        govde = "@agentickode tekrar\n\nsorun çıkaranları düzeltmek için tekrar dene"
        assert pr_komutu(govde, True) == ("duzelt", "sorun çıkaranları düzeltmek için tekrar dene")

    def test_bare_retry_stays_retry(self):
        assert pr_komutu("@agentickode tekrar", True) == ("tekrar", "")

    def test_retry_with_text_on_issue_stays_retry(self):
        assert pr_komutu("@agentickode tekrar lütfen", False)[0] == "tekrar"


class TestTekrar:
    async def test_restarts_last_failed_pr_run(self, db_session, seed_proj1, make_task_run):
        db_session.add(make_task_run(task_id="pr-test-5", status="completed"))
        db_session.add(make_task_run(task_id="pr-5", status="failed", error_message="x"))
        await db_session.commit()
        gp = SahteGitea()
        yanit = await tekrar_baslat(db_session, gp, RP, "proj-1", 5, True)
        assert "yeniden başlatıldı" in yanit
        assert gp.durum == {5: "status/review"}
        # a bare "#N" would link to Gitea issue N, not to the run
        assert "/runs/" in yanit and "](" in yanit

    async def test_reports_running_or_nothing_to_retry(self, db_session, seed_proj1, make_task_run):
        gp = SahteGitea()
        assert "bulunamadı" in await tekrar_baslat(db_session, gp, RP, "proj-1", 7, False)
        db_session.add(make_task_run(task_id="7", status="completed"))
        await db_session.commit()
        assert "başarısız değil" in await tekrar_baslat(db_session, gp, RP, "proj-1", 7, False)
        db_session.add(make_task_run(task_id="7", status="running"))
        await db_session.commit()
        assert "sürüyor" in await tekrar_baslat(db_session, gp, RP, "proj-1", 7, False)


def _push(gonderen: str, yazar: str = "agentickode", eylem: str = "synchronized") -> dict:
    return {
        "action": eylem,
        "sender": {"login": gonderen},
        "repository": {"full_name": RP},
        "pull_request": {
            "number": 5,
            "state": "open",
            "user": {"login": yazar},
            "head": {"ref": "f"},
        },
    }


class TestPushKarari:
    async def test_bot_push_ignored(self):
        assert (await push_karari(SahteGitea(), _push("agentickode"), []))["reason"] == "bot_push"

    async def test_human_push_on_bot_pr_restarts_test(self):
        gp = SahteGitea()
        gp.yanitlar[f"/repos/{RP}/contents/mvnw"] = (200, {})
        gp.etiket[5] = ["test/failed", "ai-tested"]
        karar = await push_karari(gp, _push("mozdemir"), list(gp.etiket[5]))
        assert karar["reason"] == "human_push_test"
        assert gp.etiket[5] == ["ai-test"]

    async def test_on_hold_untouched(self):
        karar = await push_karari(SahteGitea(), _push("mozdemir"), ["status/on-hold"])
        assert karar["reason"] == "test_not_on_push"

    async def test_human_pr_goes_to_ci_unless_review_requested(self):
        gp = SahteGitea()
        gp.pr[5] = {"head": {"sha": "abc123", "ref": "f"}}
        for eylem in ("opened", "synchronized"):
            karar = await push_karari(gp, _push("mozdemir", "mozdemir", eylem), [])
            assert karar["reason"] == "human_pr_ci"
        assert len(gp.dispatch) == 2
        assert await push_karari(gp, _push("mozdemir", "mozdemir"), ["ai-review"]) is None

    async def test_bot_pr_opened_left_to_label_chain(self):
        assert await push_karari(SahteGitea(), _push("mozdemir", eylem="opened"), []) is None

    async def test_human_push_on_doc_only_bot_pr_goes_to_ci(self):
        gp = SahteGitea()
        gp.yanitlar[f"/repos/{RP}/contents/mvnw"] = (200, {})
        gp.dosya[5] = ["README.md"]
        gp.pr[5] = {"head": {"sha": "abc123", "ref": "f"}}
        karar = await push_karari(gp, _push("mozdemir"), ["ai-reviewed"])
        assert karar["reason"] == "human_push_ci"
        assert gp.dispatch[0][1] == {"ref": "f", "inputs": {"sha": "abc123"}}
        assert await push_karari(gp, _push("mozdemir"), ["ai-review"]) is None


class _BlobluGitea(SahteGitea):
    """contents yanitlarini ref'e gore ayiran sahte Gitea."""

    def __init__(self):
        super().__init__()
        self.blob: dict[tuple[str, str], str] = {}

    async def _get(self, url: str, params: dict | None = None, **kw):
        yol = url.removeprefix("https://gitea.test/api/v1")
        onek = f"/repos/{RP}/contents/"
        if yol.startswith(onek) and ".gitea/workflows" not in yol and "mvnw" not in yol:
            sha = self.blob.get((yol.removeprefix(onek), (params or {}).get("ref", "")))
            veri = {"type": "file", "sha": sha} if sha else {}
            return SimpleNamespace(
                status_code=200 if sha else 404, json=lambda: veri, raise_for_status=lambda: None
            )
        return await super()._get(url, params=params, **kw)


def _birlesme_kur(dosya_hedefte: str = "b1", cakisma: bool = False) -> _BlobluGitea:
    """M = merge(P1, P2); P2 hedef dalda; P1'de ci-kapisi var; M, A.java'yi P2'den alir."""
    gp = _BlobluGitea()
    gp.yanitlar[f"/repos/{RP}/contents/mvnw"] = (200, {})
    gp.yanitlar[f"/repos/{RP}/git/commits/M"] = (
        200,
        {"parents": [{"sha": "P1"}, {"sha": "P2"}], "files": [{"filename": "A.java"}]},
    )
    gp.yanitlar[f"/repos/{RP}/compare/prj%2Fx...P2"] = (200, {"total_commits": 0})
    gp.ci_durum["P1"] = ["ci-kapisi"]
    gp.blob[("A.java", "M")] = "b2" if cakisma else "b1"
    gp.blob[("A.java", "P2")] = dosya_hedefte
    gp.pr[5] = {"head": {"sha": "M", "ref": "f"}}
    gp.etiket[5] = ["test/passed", "ai-tested", "ai-reviewed"]
    return gp


def _birlesme_push() -> dict:
    govde = _push("mozdemir")
    govde["pull_request"]["head"] = {"ref": "f", "sha": "M"}
    govde["pull_request"]["base"] = {"ref": "prj/x"}
    return govde


class TestHedefDalBirlesmesi:
    async def test_update_branch_merge_runs_only_ci(self):
        gp = _birlesme_kur()
        karar = await push_karari(gp, _birlesme_push(), list(gp.etiket[5]))
        assert karar["reason"] == "base_merge_ci"
        assert gp.etiket[5] == ["test/passed", "ai-tested", "ai-reviewed"]
        assert gp.dispatch[0][1] == {"ref": "f", "inputs": {"sha": "M"}}

    async def test_merge_with_own_change_restarts_test(self):
        gp = _birlesme_kur(cakisma=True)
        karar = await push_karari(gp, _birlesme_push(), list(gp.etiket[5]))
        assert karar["reason"] == "human_push_test"
        assert "ai-test" in gp.etiket[5]

    async def test_second_parent_outside_base_restarts_test(self):
        gp = _birlesme_kur()
        gp.yanitlar[f"/repos/{RP}/compare/prj%2Fx...P2"] = (200, {"total_commits": 1})
        karar = await push_karari(gp, _birlesme_push(), list(gp.etiket[5]))
        assert karar["reason"] == "human_push_test"

    async def test_unfinished_chain_on_previous_head_restarts_test(self):
        gp = _birlesme_kur()
        gp.ci_durum["P1"] = []
        karar = await push_karari(gp, _birlesme_push(), list(gp.etiket[5]))
        assert karar["reason"] == "human_push_test"

    async def test_single_parent_commit_restarts_test(self):
        gp = _birlesme_kur()
        gp.yanitlar[f"/repos/{RP}/git/commits/M"] = (200, {"parents": [{"sha": "P1"}]})
        karar = await push_karari(gp, _birlesme_push(), list(gp.etiket[5]))
        assert karar["reason"] == "human_push_test"

    async def test_deleted_file_matches_when_absent_in_base(self):
        gp = _birlesme_kur()
        gp.blob.clear()  # A.java ne M'de ne P2'de: hedef dalda silinmis
        karar = await push_karari(gp, _birlesme_push(), list(gp.etiket[5]))
        assert karar["reason"] == "base_merge_ci"

    async def test_api_error_falls_back_to_test(self):
        gp = _birlesme_kur()
        del gp.yanitlar[f"/repos/{RP}/git/commits/M"]
        karar = await push_karari(gp, _birlesme_push(), list(gp.etiket[5]))
        assert karar["reason"] == "human_push_test"

    async def test_pending_review_is_left_to_review_flow(self):
        gp = _birlesme_kur()
        assert await push_karari(gp, _birlesme_push(), ["ai-review"]) is None

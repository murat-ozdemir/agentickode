# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: yorum komutlari, yazma yetkisi, tekrar ve insan push'u."""

import pytest

from backend.api._bimetri_komut import inceleme_komutu, komut_ayikla, yazma_yetkisi
from backend.api._bimetri_push import push_karari
from backend.api._bimetri_tekrar import tekrar_baslat
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


class TestTekrar:
    async def test_restarts_last_failed_pr_run(self, db_session, seed_proj1, make_task_run):
        db_session.add(make_task_run(task_id="pr-test-5", status="completed"))
        db_session.add(make_task_run(task_id="pr-5", status="failed", error_message="x"))
        await db_session.commit()
        gp = SahteGitea()
        yanit = await tekrar_baslat(db_session, gp, RP, "proj-1", 5, True)
        assert "yeniden başlatıldı" in yanit
        assert gp.durum == {5: "status/review"}

    async def test_reports_running_or_nothing_to_retry(self, db_session, seed_proj1, make_task_run):
        gp = SahteGitea()
        assert "bulunamadı" in await tekrar_baslat(db_session, gp, RP, "proj-1", 7, False)
        db_session.add(make_task_run(task_id="7", status="completed"))
        await db_session.commit()
        assert "başarısız değil" in await tekrar_baslat(db_session, gp, RP, "proj-1", 7, False)
        db_session.add(make_task_run(task_id="7", status="running"))
        await db_session.commit()
        assert "sürüyor" in await tekrar_baslat(db_session, gp, RP, "proj-1", 7, False)


def _push(gonderen: str, yazar: str = "agentickode") -> dict:
    return {
        "sender": {"login": gonderen},
        "repository": {"full_name": RP},
        "pull_request": {"number": 5, "state": "open", "user": {"login": yazar}, "head": {"ref": "f"}},
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

    async def test_human_pr_or_on_hold_untouched(self):
        gp = SahteGitea()
        assert await push_karari(gp, _push("mozdemir", yazar="mozdemir"), []) is None
        karar = await push_karari(gp, _push("mozdemir"), ["status/on-hold"])
        assert karar["reason"] == "test_not_on_push"

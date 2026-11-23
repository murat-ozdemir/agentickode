# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 5): an open question stops the loop and asks a human."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.worker.flow import _bimetri_kapsam as kapsam
from backend.worker.flow._bimetri_agent_rules import OPEN_QUESTION_RULES
from backend.worker.phases import finalization
from backend.worker.phases._bimetri_oto import bekletildi_mi
from backend.worker.phases._bimetri_soru import SORU_BASLIGI, acik_soru, soru_karari
from tests.unit.bimetri_sahte import SahteGitea

RP = "org/repo"
RAPOR = (
    "## Test raporu\n- kriter 1 → `ATest`\n\n"
    "### Açık soru\nSeri no boşsa 400 mü dönmeli, 422 mi? @biri baksın\n\n"
    "**Sonuç:** Testler kaldı"
)


def _gitea(yazar: str = "agentickode", etiket: list[str] | None = None):
    gp = SahteGitea()
    gp.pr[5] = {"state": "open", "merged": False, "user": {"login": yazar}, "body": "Closes #1"}
    gp.yorum[5] = []
    gp.etiket[5] = etiket or []
    gp.etiket[1] = []
    return gp


class TestAcikSoru:
    def test_returns_the_section_up_to_the_result_line(self):
        assert acik_soru(RAPOR) == "Seri no boşsa 400 mü dönmeli, 422 mi? @biri baksın"

    def test_stops_at_the_next_heading(self):
        rapor = "### Açık Soru\nA mı B mi?\n### Öneriler\n- x"
        assert acik_soru(rapor) == "A mı B mi?"

    def test_none_without_heading_or_with_empty_section(self):
        assert acik_soru("**Sonuç:** Testler geçti") is None
        assert acik_soru("### Açık soru\nYok.\n\n**Sonuç:** Testler geçti") is None
        assert acik_soru("") is None

    def test_mentioning_open_question_in_text_is_not_a_question(self):
        assert acik_soru("Raporda 'Açık soru' yok.\n**Sonuç:** Testler geçti") is None


class TestSoruKarari:
    async def test_puts_pr_and_issue_on_hold_and_posts_the_question(self):
        gp = _gitea()
        assert await soru_karari(gp, RP, 5, RAPOR, 21)
        assert gp.durum == {5: "status/on-hold", 1: "status/on-hold"}
        yorum = gp.yorum[5][-1]
        assert "açık soru" in yorum and "400 mü dönmeli" in yorum
        assert "devam <yanıt>" in yorum
        assert "@agentickode" not in yorum and "@biri" not in yorum
        assert bekletildi_mi(21)

    async def test_no_question_changes_nothing(self):
        gp = _gitea()
        assert not await soru_karari(gp, RP, 5, "**Sonuç:** Testler geçti", 22)
        assert gp.durum == {} and gp.yorum[5] == []

    async def test_skipped_on_human_or_on_hold_pr(self):
        gp = _gitea(yazar="mozdemir")
        assert not await soru_karari(gp, RP, 5, RAPOR, 23)
        gp = _gitea(etiket=["status/on-hold"])
        assert not await soru_karari(gp, RP, 5, RAPOR, 24)
        assert gp.yorum[5] == []


class TestKural:
    def test_rule_names_the_parsed_heading(self):
        assert f"'{SORU_BASLIGI}'" in OPEN_QUESTION_RULES
        assert "yanlış bir tahmin sonradan geri alınmayı gerektirecekse" in OPEN_QUESTION_RULES
        assert "Başka hiçbir durumda bu başlığı yazma" in OPEN_QUESTION_RULES

    async def test_every_agent_gets_the_rule(self, make_task_run):
        run = make_task_run(git_provider="github", repo_owner="org", repo_name="repo")
        for tur in ("inceleme", "test", "duzeltme"):
            assert OPEN_QUESTION_RULES in await kapsam.kapsam_eki(run, None, tur)


class TestReviewFinalize:
    @pytest.fixture(autouse=True)
    async def _project_parent(self, db_session):
        from backend.models import ProjectConfig

        db_session.add(
            ProjectConfig(project_id="proj-1", project_slug="x", repo_owner="o", repo_name="r")
        )
        await db_session.commit()

    async def _finalize(self, db_session, make_task_run, mock_services, ozet: str):
        run = make_task_run(
            pr_url=None,
            git_provider="gitea",
            repo_owner="org",
            repo_name="repo",
            task_source_meta={"pr_number": 9, "review_mode": "comment"},
            review_result={"approved": False, "issues": [], "summary": ozet},
        )
        db_session.add(run)
        await db_session.commit()
        f = "backend.worker.phases.finalization"
        soru, ci, oto = AsyncMock(return_value=True), AsyncMock(return_value="ci"), AsyncMock()
        with (
            patch(f"{f}.get_git_provider", new=MagicMock(return_value=MagicMock())),
            patch(f"{f}.get_project_token", new=AsyncMock(return_value="t")),
            patch(f"{f}.get_http_client", new=MagicMock()),
            patch(f"{f}.broadcaster", new=MagicMock(log=AsyncMock(), event=AsyncMock())),
            patch(f"{f}._post_review_comment", new=AsyncMock()),
            patch(f"{f}._flip_review_label", new=AsyncMock()),
            patch(f"{f}.kosu_soru_karari", new=soru),
            patch(f"{f}.ci_baslat", new=ci),
            patch(f"{f}._bimetri_oto_duzeltme", new=oto),
        ):
            await finalization.run(run, db_session, mock_services)
        return soru, ci, oto

    async def test_question_stops_instead_of_fix_round_or_ci(
        self, db_session, make_task_run, mock_services
    ):
        ozet = "bulgular\n### Açık soru\n400 mü 422 mi?\n\n**Sonuç:** Birleştirilebilir"
        soru, ci, oto = await self._finalize(db_session, make_task_run, mock_services, ozet)
        soru.assert_awaited_once()
        oto.assert_not_awaited()
        ci.assert_not_awaited()

    async def test_without_question_mergeable_review_starts_ci(
        self, db_session, make_task_run, mock_services
    ):
        ozet = "bulgular\n\n**Sonuç:** Birleştirilebilir"
        soru, ci, oto = await self._finalize(db_session, make_task_run, mock_services, ozet)
        soru.assert_not_awaited()
        ci.assert_awaited_once()

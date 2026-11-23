# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: the PR-comment fix run receives the PR's earlier discussion."""

from types import SimpleNamespace

from backend.api import _bimetri_pr_context as ctx
from backend.api._bimetri_pr_context import discussion_section, pr_discussion
from backend.services.git.gitea import GiteaProvider
from tests.unit.bimetri_sahte import SahteGitea

RP = "org/repo"
TRIGGER = {"id": 30, "created_at": "2026-11-19T19:52:04+03:00", "body": "@agentickode duzelt"}


def _comment(cid: int, when: str, body: str, user: str = "agentickode") -> dict:
    return {"id": cid, "created_at": when, "body": body, "user": {"login": user}}


def _gitea_with_discussion() -> SahteGitea:
    gp = SahteGitea()
    gp.yanitlar[f"/repos/{RP}/issues/10/comments"] = (
        200,
        [
            _comment(10, "2026-11-19T19:32:29+03:00", "## AI Test Raporu\nTestler gecti"),
            _comment(20, "2026-11-19T19:34:37+03:00", "## AI Kod Incelemesi\n- dusuk: aufnr"),
            TRIGGER | {"user": {"login": "mozdemir"}},
            _comment(40, "2026-11-19T19:54:12+03:00", "Duzeltme push edildi"),
        ],
    )
    gp.yanitlar[f"/repos/{RP}/pulls/10/reviews"] = (
        200,
        [
            {
                "id": 1,
                "submitted_at": "2026-11-19T19:40:00+03:00",
                "state": "REQUEST_CHANGES",
                "body": "",
                "comments_count": 1,
                "user": {"login": "mozdemir"},
            },
            {
                "id": 2,
                "submitted_at": "2026-11-19T20:00:00+03:00",
                "state": "COMMENT",
                "body": "sonra yazildi",
                "user": {"login": "mozdemir"},
            },
        ],
    )
    gp.yanitlar[f"/repos/{RP}/pulls/10/reviews/1/comments"] = (
        200,
        [{"path": "A.java", "position": 12, "body": "null kontrolu eksik"}],
    )
    return gp


class TestPrDiscussion:
    async def test_starts_from_the_last_report_and_keeps_reviews_after_it(self):
        text = await pr_discussion(_gitea_with_discussion(), RP, 10, TRIGGER)

        assert "AI Test Raporu" not in text  # older round: the notebook carries it
        assert text.index("AI Kod Incelemesi") < text.index("null kontrolu eksik")
        assert "`A.java:12` null kontrolu eksik" in text
        assert "inceleme (REQUEST_CHANGES)" in text

    async def test_excludes_trigger_and_later_items(self):
        text = await pr_discussion(_gitea_with_discussion(), RP, 10, TRIGGER)

        assert "@agentickode duzelt" not in text
        assert "Duzeltme push edildi" not in text
        assert "sonra yazildi" not in text

    async def test_keeps_human_comments_after_the_last_report_only(self):
        gp = SahteGitea()
        gp.yanitlar[f"/repos/{RP}/issues/10/comments"] = (
            200,
            [
                _comment(1, "2026-11-19T10:00:00+03:00", "## AI Test Raporu\neski rapor"),
                _comment(2, "2026-11-19T11:00:00+03:00", "eski not", user="mozdemir"),
                _comment(3, "2026-11-19T12:00:00+03:00", "## Koşu durdu: [#5](u)\nyeni"),
                _comment(4, "2026-11-19T12:30:00+03:00", "## Notlar\nbir", user="mozdemir"),
                _comment(5, "2026-11-19T13:00:00+03:00", "iki", user="mozdemir"),
            ],
        )
        gp.yanitlar[f"/repos/{RP}/pulls/10/reviews"] = (200, [])

        text = await pr_discussion(gp, RP, 10, TRIGGER)

        assert "eski rapor" not in text and "eski not" not in text
        assert text.startswith("### agentickode") and "## Koşu durdu" in text
        assert "bir" in text and "iki" in text

    async def test_keeps_all_comments_when_no_report_yet(self):
        gp = SahteGitea()
        gp.yanitlar[f"/repos/{RP}/issues/10/comments"] = (
            200,
            [
                _comment(1, "2026-11-19T10:00:00+03:00", "ilk", user="mozdemir"),
                _comment(2, "2026-11-19T11:00:00+03:00", "ikinci", user="mozdemir"),
            ],
        )
        gp.yanitlar[f"/repos/{RP}/pulls/10/reviews"] = (200, [])

        text = await pr_discussion(gp, RP, 10, TRIGGER)

        assert "ilk" in text and "ikinci" in text

    async def test_auto_round_gets_nothing_because_its_trigger_carries_the_report(self):
        trigger = TRIGGER | {"body": "@agentickode duzelt\n<!-- agentickode-oto -->\n\nrapor"}

        assert await pr_discussion(_gitea_with_discussion(), RP, 10, trigger) == ""

    async def test_caps_each_entry(self, monkeypatch):
        monkeypatch.setattr(ctx, "ENTRY_CHARS", 40)

        text = await pr_discussion(_gitea_with_discussion(), RP, 10, TRIGGER)

        assert all(len(part) <= 40 for part in text.split("\n\n### "))

    async def test_returns_empty_when_api_fails(self):
        gp = SahteGitea()
        gp.yanitlar[f"/repos/{RP}/issues/10/comments"] = (500, {})
        gp.yanitlar[f"/repos/{RP}/pulls/10/reviews"] = (500, {})

        assert await pr_discussion(gp, RP, 10, TRIGGER) == ""


class TestDiscussionSection:
    def test_empty_discussion_adds_nothing(self):
        assert discussion_section("") == ""

    def test_wraps_discussion_for_the_agent(self):
        section = discussion_section("### a\n\nbulgu")

        assert "<pr_discussion>\n\n### a\n\nbulgu\n\n</pr_discussion>" in section
        assert "bulgular" in section

    def test_tells_agent_to_fix_suggestions_even_when_mergeable(self):
        section = discussion_section("### a\n\nbulgu")

        assert '"Oneriler"' in section
        assert "Birlestirilebilir" in section


class TestGiteaGetPrComments:
    async def test_returns_reviews_and_plain_comments(self):
        gp = _gitea_with_discussion()
        provider = GiteaProvider(SimpleNamespace(get=gp._get), base_url=gp._base_url, token="t")

        items = await provider.get_pr_comments(RP, 10)

        bodies = [i.get("body") for i in items]
        assert "sonra yazildi" in bodies
        assert any("AI Kod Incelemesi" in (b or "") for b in bodies)

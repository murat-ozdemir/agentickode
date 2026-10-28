# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: otomatik duzeltme tur siniri ve zorluk artirma."""

from backend.worker.phases._bimetri_oto import (
    DEVAM_ISARET,
    OTO_ISARET,
    bekletildi_mi,
    oto_tur_karari,
    oto_tur_sayisi,
    zorluk_artir,
)
from tests.unit.bimetri_sahte import SahteGitea

RP = "org/repo"


def _gitea(oto: int = 0, pr_zorluk: str | None = "easy", issue_zorluk: str | None = "easy"):
    gp = SahteGitea()
    gp.pr[5] = {"state": "open", "merged": False, "user": {"login": "agentickode"}, "body": "Closes #1"}
    gp.yorum[5] = [f"@agentickode duzelt\n{OTO_ISARET}"] * oto
    gp.etiket[5] = [f"difficulty/{pr_zorluk}"] if pr_zorluk else []
    gp.etiket[1] = [f"difficulty/{issue_zorluk}"] if issue_zorluk else []
    return gp


class TestTurSayisi:
    async def test_counts_auto_comments_since_last_continue(self):
        gp = _gitea(oto=2)
        gp.yorum[5] += [f"devam\n{DEVAM_ISARET}", f"x {OTO_ISARET}", "insan yorumu"]
        assert await oto_tur_sayisi(gp, RP, 5) == 1


class TestTurKarari:
    async def test_first_rounds_allowed_without_bump(self):
        gp = _gitea(oto=1)
        assert await oto_tur_karari(gp, RP, 5, "testler kaldi", 11)
        assert gp.etiket[5] == ["difficulty/easy"]

    async def test_third_round_bumps_difficulty(self):
        gp = _gitea(oto=2)
        assert await oto_tur_karari(gp, RP, 5, "testler kaldi", 11)
        assert gp.etiket[5] == ["difficulty/medium"]

    async def test_limit_puts_pr_and_issue_on_hold(self):
        gp = _gitea(oto=3)
        assert not await oto_tur_karari(gp, RP, 5, "testler kaldi", 12)
        assert gp.durum == {5: "status/on-hold", 1: "status/on-hold"}
        assert "3 tur doldu" in gp.yorum[5][-1]
        assert "@agentickode" not in gp.yorum[5][-1]
        assert bekletildi_mi(12) and not bekletildi_mi(12)

    async def test_skipped_on_hold_or_human_pr(self):
        gp = _gitea()
        gp.etiket[5].append("status/on-hold")
        assert not await oto_tur_karari(gp, RP, 5, "x")
        gp = _gitea()
        gp.pr[5]["user"] = {"login": "mozdemir"}
        assert not await oto_tur_karari(gp, RP, 5, "x")


class TestZorlukArtir:
    async def test_skips_when_human_changed_pr_difficulty(self):
        gp = _gitea(pr_zorluk="hard", issue_zorluk="easy")
        assert await zorluk_artir(gp, RP, 5, 1) is None

    async def test_skips_at_top(self):
        gp = _gitea(pr_zorluk="hard", issue_zorluk="hard")
        assert await zorluk_artir(gp, RP, 5, 1) is None

    async def test_defaults_to_easy_when_unlabelled(self):
        gp = _gitea(pr_zorluk=None, issue_zorluk=None)
        assert await zorluk_artir(gp, RP, 5, 1) == "medium"

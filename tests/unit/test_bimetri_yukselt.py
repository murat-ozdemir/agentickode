# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 6): raising the difficulty stops and asks first."""

from backend.api._bimetri_komut import devam_isareti
from backend.worker.phases._bimetri_oto import DEVAM_ISARET, OTO_ISARET, oto_tur_karari
from backend.worker.phases._bimetri_yukselt import bekleyen_yukseltme, sonraki_zorluk
from tests.unit.bimetri_sahte import SahteGitea

RP = "org/repo"


def _gitea(pr_zorluk: str | None = "easy", issue_zorluk: str | None = "easy", oto: int = 0):
    gp = SahteGitea()
    gp.pr[5] = {"state": "open", "merged": False, "user": {"login": "agentickode"}, "body": ""}
    gp.yorum[5] = [f"@agentickode duzelt\n{OTO_ISARET}"] * oto
    gp.etiket[5] = [f"difficulty/{pr_zorluk}"] if pr_zorluk else []
    gp.etiket[1] = [f"difficulty/{issue_zorluk}"] if issue_zorluk else []
    return gp


async def _sorulmus(**kw) -> SahteGitea:
    gp = _gitea(oto=2, **kw)
    gp.pr[5]["body"] = "Closes #1"
    assert not await oto_tur_karari(gp, RP, 5, "testler kaldi", 31)
    gp.etiket[5].remove("status/on-hold")  # insanin @agentickode yorumu etiketi kaldirir
    return gp


class TestSonrakiZorluk:
    async def test_next_level_from_the_pr_label(self):
        assert await sonraki_zorluk(_gitea(), RP, 5, 1) == ("easy", "easy", "medium")

    async def test_skips_when_human_changed_pr_difficulty(self):
        assert await sonraki_zorluk(_gitea(pr_zorluk="hard"), RP, 5, 1) is None

    async def test_skips_at_top(self):
        gp = _gitea(pr_zorluk="hard", issue_zorluk="hard")
        assert await sonraki_zorluk(gp, RP, 5, 1) is None

    async def test_defaults_to_easy_when_unlabelled(self):
        gp = _gitea(pr_zorluk=None, issue_zorluk=None)
        assert await sonraki_zorluk(gp, RP, 5, 1) == (None, "easy", "medium")


class TestDevam:
    async def test_continue_applies_the_asked_raise_and_resets_the_counter(self):
        gp = await _sorulmus()
        await devam_isareti(gp, RP, 5, "mozdemir", 1)
        assert "difficulty/medium" in gp.etiket[5] and "difficulty/easy" not in gp.etiket[5]
        assert DEVAM_ISARET in gp.yorum[5][-1] and "difficulty/medium" in gp.yorum[5][-1]

    async def test_raise_is_applied_once(self):
        gp = await _sorulmus()
        await devam_isareti(gp, RP, 5, "mozdemir", 1)
        assert await bekleyen_yukseltme(gp, RP, 5, 1) is None
        assert gp.etiket[5].count("difficulty/medium") == 1

    async def test_human_label_change_wins(self):
        gp = await _sorulmus()
        gp.etiket[5] = ["difficulty/hard"]
        await devam_isareti(gp, RP, 5, "mozdemir", 1)
        assert gp.etiket[5] == ["difficulty/hard"]

    async def test_continue_without_a_question_only_resets(self):
        gp = _gitea()
        await devam_isareti(gp, RP, 5, "mozdemir", 1)
        assert gp.etiket[5] == ["difficulty/easy"]
        assert "yükseltildi" not in gp.yorum[5][-1]

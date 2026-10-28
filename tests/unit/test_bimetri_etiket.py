# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: PR acilis etiketleri ve istege bagli AI incelemesi."""

from backend.worker.phases._bimetri_etiket import (
    ajan_adi,
    inceleme_baslat,
    inceleme_istendi,
    issue_no_bul,
    pr_acilis_etiketleri,
)
from tests.unit.bimetri_sahte import SahteGitea

RP = "org/repo"


class TestYardimcilar:
    def test_issue_no_from_closes_line(self):
        assert issue_no_bul("Bir sey yaptim.\n\nCloses #42") == 42
        assert issue_no_bul("fixes #7 ve closes #8") == 7
        assert issue_no_bul(None) is None

    def test_agent_name_from_provider_label(self):
        assert ajan_adi("agent/claude@agent-1") == "claude"
        assert ajan_adi("codex") == "codex"
        assert ajan_adi(None) is None


class TestPrAcilisEtiketleri:
    async def test_copies_difficulty_and_picks_opposite_test_agent(self):
        gp = SahteGitea()
        gp.etiket[1] = ["difficulty/medium", "agent/claude"]
        konan = await pr_acilis_etiketleri(gp, RP, 5, 1, "agent/claude@agent-1", True)
        assert konan == ["difficulty/medium", "test-agent/codex", "ai-test"]
        assert gp.etiket[5][-1] == "ai-test"

    async def test_issue_test_agent_wins_over_opposite(self):
        gp = SahteGitea()
        gp.etiket[1] = ["test-agent/claude"]
        konan = await pr_acilis_etiketleri(gp, RP, 5, 1, "claude", True)
        assert "test-agent/claude" in konan

    async def test_no_mvnw_adds_review_only_when_issue_asks(self):
        gp = SahteGitea()
        gp.etiket[1] = ["difficulty/easy"]
        assert await pr_acilis_etiketleri(gp, RP, 5, 1, "claude", False) == ["difficulty/easy"]
        gp.etiket[1].append("ai-review")
        assert "ai-review" in await pr_acilis_etiketleri(gp, RP, 6, 1, "claude", False)

    async def test_without_issue_only_test_labels(self):
        gp = SahteGitea()
        assert await pr_acilis_etiketleri(gp, RP, 5, None, "codex", True) == [
            "test-agent/claude",
            "ai-test",
        ]


class TestInceleme:
    async def test_requested_via_pr_or_issue(self):
        gp = SahteGitea()
        assert not await inceleme_istendi(gp, RP, 5, 1)
        gp.etiket[1] = ["ai-review"]
        assert await inceleme_istendi(gp, RP, 5, 1)
        assert await inceleme_istendi(gp, RP, 1, None)

    async def test_start_replaces_reviewed_with_review(self):
        gp = SahteGitea()
        gp.etiket[5] = ["ai-reviewed", "test/passed"]
        await inceleme_baslat(gp, RP, 5)
        assert gp.etiket[5] == ["test/passed", "ai-review"]

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 3): the test agent's difficulty tier and effort."""

import pytest

from backend.worker.flow._bimetri_test_level import effort_for_test, label_value, tier_for_test


class TestTestEffort:
    @pytest.mark.parametrize(
        ("chosen", "used"),
        [
            ("max", "high"),
            ("xhigh", "high"),
            ("high", "medium"),
            ("medium", "low"),
            ("low", "low"),
        ],
    )
    def test_one_level_below_capped_at_high(self, chosen, used):
        assert effort_for_test(chosen) == used

    def test_no_effort_keeps_the_model_default(self):
        assert effort_for_test("") == ""


class TestTestTier:
    def test_uses_the_issue_difficulty_not_the_raised_pr_one(self):
        assert tier_for_test(["status/review", "difficulty/Easy"], "HARD") == "EASY"

    def test_keeps_the_tier_when_the_issue_has_none(self):
        assert tier_for_test(["status/review"], "MEDIUM") == "MEDIUM"
        assert tier_for_test([], "EASY") == "EASY"

    def test_label_value_normalises_like_the_executor(self):
        assert label_value([" Difficulty/Hard "], "difficulty") == "hard"
        assert label_value(["effort/high"], "difficulty") is None

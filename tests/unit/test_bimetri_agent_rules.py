# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency items 1-2): test and fix agent prompt rules."""

from backend.worker.flow import executor
from backend.worker.flow._bimetri_agent_rules import (
    FIX_RULES,
    TARGETED_IT,
    TARGETED_TEST,
    TEST_RULES,
)


class TestTestRules:
    def test_checks_each_acceptance_criterion_with_a_targeted_test(self):
        assert "her kabul kriteri için en az bir hedefli test" in TEST_RULES
        assert "kabul kriteri yoksa istenen davranışı tek kriter say" in TEST_RULES

    def test_edge_cases_go_to_the_report_not_into_tests(self):
        assert "Kriterlerin dışında test yazma" in TEST_RULES
        assert "'### Öneriler'" in TEST_RULES

    def test_leaves_the_whole_suite_to_the_ci_gate(self):
        assert "Tüm test takımını çalıştırma" in TEST_RULES
        assert "CI kapısı" in TEST_RULES
        assert TARGETED_TEST in TEST_RULES and TARGETED_IT in TEST_RULES
        assert "sh mvnw -q verify" not in TEST_RULES

    def test_targeted_commands_run_named_tests_only(self):
        assert "-Dtest='ATest,BTest'" in TARGETED_TEST
        assert "-Dsurefire.failIfNoSpecifiedTests=false" in TARGETED_TEST
        assert "-Dtest=None" in TARGETED_IT and "-Dit.test=" in TARGETED_IT

    def test_keeps_the_fixed_result_lines(self):
        for line in ("Testler geçti", "Testler kaldı", "Test edilemedi"):
            assert f"'**Sonuç:** {line}'" in TEST_RULES

    def test_executor_uses_the_module_rules(self):
        assert executor.TEST_RULES is TEST_RULES


class TestFixRules:
    def test_runs_failing_and_changed_class_tests_only(self):
        assert "Tüm test takımını çalıştırma" in FIX_RULES
        assert "başarısız testleri ve değiştirdiğin sınıfların testlerini" in FIX_RULES
        assert TARGETED_TEST in FIX_RULES and TARGETED_IT in FIX_RULES

    def test_overrides_the_agents_md_test_command(self):
        assert "AGENTS.md'den önceliklidir" in FIX_RULES

    def test_executor_uses_the_module_rules(self):
        assert executor.FIX_RULES is FIX_RULES

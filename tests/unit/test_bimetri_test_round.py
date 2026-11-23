# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a review that only finds missing tests starts a test round, not a fix."""

from types import SimpleNamespace

import pytest

import backend.services.git as git_pkg
from backend.worker.phases import _bimetri_test_round as tr
from backend.worker.phases import _helpers, finalization
from backend.worker.phases._bimetri_oto import oto_tur_sayisi
from tests.unit.bimetri_sahte import SahteGitea

# The PR 118 review: both findings point at test files
TEST_ONLY = """Atomik DAO çağrıları doğrudan devrediliyor.

### Bulgular

- **Orta** — [TeracomResourceStatusServiceTest.java:42](/w/PlatformBackend/src/test/java/a/TeracomResourceStatusServiceTest.java:42): Alarm ve röle satırları için test yok.
- **Orta** — [ResourceStatusServiceAtomicTest.java:35](/w/BackendCommons/src/test/java/b/ResourceStatusServiceAtomicTest.java:35): `lastViolationType` doğrulaması yok.

### Öneriler

Eksik matris senaryolarını test edin.

**Sonuç:** Değişiklik gerekli"""

APP_FINDING = (
    "- **Kritik** — [Service.java:10](/w/src/main/java/Service.java:10): Null kontrolü yok.\n"
)


def _run(meta=None, provider="gitea"):
    return SimpleNamespace(
        id=7,
        task_source_meta={"pr_number": 10, **(meta or {})},
        git_provider=provider,
        repo_owner="org",
        repo_name="repo",
    )


def test_findings_on_test_files_only_go_to_the_test_agent():
    assert tr.only_test_findings(TEST_ONLY)


def test_a_finding_in_app_code_still_goes_to_the_fix_agent():
    mixed = TEST_ONLY.replace("### Öneriler", APP_FINDING + "\n### Öneriler")
    assert not tr.only_test_findings(mixed)


def test_the_reviewer_tag_marks_a_test_finding_on_an_app_file():
    tagged = "### Bulgular\n\n- [test] **Orta** — [Service.java:10](/w/src/main/Service.java:10): Testi yok.\n"
    assert tr.only_test_findings(tagged)
    assert tr.only_test_findings("### Bulgular\n- **Düşük** `tests/unit/test_x.py:3` eksik\n")


@pytest.mark.parametrize("summary", ["", "Bulgu yok.\n\n**Sonuç:** Birleştirilebilir"])
def test_no_findings_is_no_test_round(summary):
    assert not tr.only_test_findings(summary)


def test_the_test_round_comment_counts_as_a_round_but_starts_no_fix():
    assert "@agentickode" not in tr.TEST_ROUND_PREFIX


async def test_a_test_round_counts_toward_the_round_limit():
    gp = SahteGitea()
    gp.yorum[10] = [tr.TEST_ROUND_PREFIX + TEST_ONLY]
    assert await oto_tur_sayisi(gp, "org/repo", 10) == 1


@pytest.fixture
def gitea(monkeypatch):
    gp = SahteGitea()

    async def token(*_a):
        return "t"

    monkeypatch.setattr(git_pkg, "get_git_provider", lambda *_a, **_k: gp)
    monkeypatch.setattr(_helpers, "get_project_token", token)
    return gp


async def test_the_test_run_gets_the_review_findings(gitea):
    gitea.yorum[10] = ["## AI Test Raporu\neski", tr.TEST_ROUND_PREFIX + TEST_ONLY, "insan notu"]
    section = await tr.test_request_section(_run(), None)
    assert "Alarm ve röle satırları için test yok." in section
    assert "<!--" not in section and "düzeltme yerine" not in section


async def test_a_later_test_report_closes_the_request(gitea):
    gitea.yorum[10] = [tr.TEST_ROUND_PREFIX + TEST_ONLY, "## AI Test Raporu\nyeni"]
    assert await tr.test_request_section(_run(), None) == ""


async def test_runs_off_gitea_or_without_a_pr_get_nothing(gitea):
    gitea.yorum[10] = [tr.TEST_ROUND_PREFIX + TEST_ONLY]
    assert await tr.test_request_section(_run(provider="github"), None) == ""
    run = _run()
    run.task_source_meta = {"issue_number": 3}
    assert await tr.test_request_section(run, None) == ""


async def test_the_test_round_puts_ai_test_and_clears_old_test_labels(monkeypatch):
    gp = SahteGitea()
    gp.etiket[10] = ["ai-reviewed", "ai-tested", "test/passed"]

    async def token(*_a):
        return "t"

    monkeypatch.setattr(finalization, "get_git_provider", lambda *_a, **_k: gp)
    monkeypatch.setattr(finalization, "get_project_token", token)
    await finalization._bimetri_test_turu_etiketi(_run(), 10, None)
    assert gp.etiket[10] == ["ai-test"]

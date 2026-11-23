# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: the note a run posts on its PR (or issue) when it starts."""

from types import SimpleNamespace

import pytest

import backend.services.git as git_pkg
from backend.api._bimetri_pr_context import START_MARKER as CONTEXT_MARKER
from backend.api._bimetri_pr_context import pr_discussion
from backend.worker.phases import _bimetri_start_note as note
from backend.worker.phases import _helpers
from backend.worker.phases._bimetri_oto import OTO_ISARET, OTO_YORUM
from tests.unit.bimetri_sahte import SahteGitea


def _run(meta: dict, provider: str = "gitea") -> SimpleNamespace:
    return SimpleNamespace(
        id=312, task_source_meta=meta, git_provider=provider, repo_owner="org", repo_name="repo"
    )


def test_reads_the_reason_of_an_automatic_round():
    body = OTO_YORUM.format(neden="Test ajanı başarısız testler buldu (rapor aşağıda).")
    assert note.auto_reason(body) == "Test ajanı başarısız testler buldu (rapor aşağıda)."
    assert note.auto_reason("@agentickode şu testi düzelt") is None


@pytest.mark.parametrize(
    ("mode", "kind"),
    [("test", "Test"), ("fix", "Düzeltme"), ("comment", "İnceleme"), (None, "Görev")],
)
def test_names_the_kind_of_run(mode, kind):
    assert note.run_kind({"review_mode": mode}) == kind


def test_fix_round_note_has_reason_agent_and_round():
    meta = {"review_mode": "fix", "start_reason": "CI kaldı; aşağıdaki hatayı gider."}
    text = note.start_note(_run(meta), "codex", "gpt-5.5", "high", "2/3")
    assert "**Koşu #312 başladı: Düzeltme**" in text
    assert "/runs/312" in text
    assert "Neden: CI kaldı; aşağıdaki hatayı gider." in text
    assert "Ajan: codex (gpt-5.5, high)" in text and "Otomatik tur: 2/3" in text
    assert text.endswith(note.START_MARKER) and "@agentickode" not in text


def test_label_runs_name_their_label_and_tasks_need_no_reason():
    assert "Neden: `ai-test` etiketi" in note.start_note(
        _run({"review_mode": "test"}), "claude", None, None
    )
    assert "`ai-review` etiketi" in note.start_note(
        _run({"review_mode": "comment"}), None, None, None
    )
    task = note.start_note(_run({"issue_number": 7}), "claude", None, "")
    assert "Neden" not in task and "Ajan: claude\n" in task


def test_target_is_the_pr_then_the_issue_and_only_on_gitea():
    assert note.note_target(_run({"pr_number": 10, "issue_number": 7})) == ("org/repo", 10)
    assert note.note_target(_run({"issue_number": 7, "repo_full_name": "a/b"})) == ("a/b", 7)
    assert note.note_target(_run({"pr_number": 10}, provider="github")) is None
    assert note.note_target(_run({})) is None


@pytest.fixture
def gitea(monkeypatch):
    gp = SahteGitea()

    async def post_pr_comment(rp, n, body):
        gp.yorum.setdefault(n, []).append(body)

    async def token(*_a):
        return "t"

    gp.post_pr_comment = post_pr_comment
    monkeypatch.setattr(git_pkg, "get_git_provider", lambda *_a, **_k: gp)
    monkeypatch.setattr(_helpers, "get_project_token", token)
    return gp


async def test_posts_the_note_with_the_automatic_round_count(gitea):
    gitea.yorum[10] = [OTO_YORUM.format(neden="a"), OTO_YORUM.format(neden="b")]
    meta = {"pr_number": 10, "review_mode": "fix", "auto_round": True}
    await note.announce_start(_run(meta), None, "codex", None, None)
    assert "Otomatik tur: 2/3" in gitea.yorum[10][-1]


async def test_a_failing_post_does_not_stop_the_run(gitea):
    async def broken(*_a):
        raise RuntimeError("gitea down")

    gitea.post_pr_comment = broken
    await note.announce_start(_run({"pr_number": 10}), None, "codex", None, None)


async def test_start_notes_stay_out_of_the_agents_pr_history():
    assert CONTEXT_MARKER == note.START_MARKER
    gp = SahteGitea()
    start = note.start_note(_run({"review_mode": "test"}), "claude", None, None)
    gp.yanitlar["/repos/org/repo/issues/10/comments"] = (
        200,
        [
            {"id": 1, "created_at": "1", "body": start, "user": {"login": "agentickode"}},
            {"id": 2, "created_at": "2", "body": "eski yorum", "user": {"login": "m"}},
        ],
    )
    gp.yanitlar["/repos/org/repo/pulls/10/reviews"] = (200, [])
    text = await pr_discussion(gp, "org/repo", 10, {"id": 9, "body": "@agentickode x"})
    assert "eski yorum" in text and "Koşu #312" not in text
    assert OTO_ISARET not in start

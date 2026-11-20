# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Slack run messages name the run type, issue/PR, server and result."""

from backend.services.notifications.formatter import format_notification


def _data(**kw):
    base = {
        "run_id": 152,
        "title": "SAP-ORG-2.1 Kat değişiminde yeni organizasyon aç",
        "project_id": "bienport-iot-platform-reporting",
        "repo": "platform-reporting",
        "run_kind": "task",
        "issue_number": "5",
        "server": "worker-2",
    }
    return {**base, **kw}


def test_coding_run_started_names_type_issue_and_server():
    lines = format_notification("run_started", _data()).splitlines()
    assert lines[0] == "🛠️ Kodlama başladı · platform-reporting"
    assert lines[1] == "📌 Issue #5 — SAP-ORG-2.1 Kat değişiminde yeni organizasyon aç"
    assert lines[2] == "⚙️ Koşu #152 · worker-2"
    assert lines[3].endswith("/runs/152")


def test_coding_run_completed_shows_pr_agent_and_duration():
    msg = format_notification(
        "run_completed",
        _data(
            pr_url="https://git.example/pulls/11",
            agent="codex",
            model="gpt-6.1-terra",
            duration_seconds=130,
        ),
    )
    assert msg.startswith("✅ 🛠️ Kodlama bitti · platform-reporting")
    assert "🔀 PR: https://git.example/pulls/11" in msg
    assert "⚙️ Koşu #152 · worker-2 · codex (gpt-6.1-terra) · ⏱️ 2m 10s" in msg


def test_failed_tests_get_a_warning_and_the_result():
    msg = format_notification(
        "run_completed",
        _data(
            run_id=153,
            run_kind="test",
            pr_number="11",
            title="[PR #11] Test: SAP-ORG-2.1 Kat değişiminde yeni organizasyon aç",
            outcome="Testler kaldı",
        ),
    )
    lines = msg.splitlines()
    assert lines[0] == "⚠️ 🧪 Test bitti · platform-reporting"
    assert lines[1] == "📌 PR #11 (Issue #5) — SAP-ORG-2.1 Kat değişiminde yeni organizasyon aç"
    assert "📋 Sonuç: Testler kaldı" in lines


def test_review_uses_pr_title_and_mergeable_is_success():
    msg = format_notification(
        "run_completed",
        _data(
            run_kind="review",
            issue_number=None,
            pr_number="11",
            pr_title="SAP-ORG-2.1 Kat değişiminde yeni organizasyon aç",
            title="Review PR #11: SAP-ORG-2.1 Kat değişiminde yeni organizasyon aç",
            outcome="Birleştirilebilir",
        ),
    )
    assert msg.startswith("✅ 🔍 İnceleme bitti")
    assert "📌 PR #11 — SAP-ORG-2.1 Kat değişiminde yeni organizasyon aç" in msg


def test_fix_run_shows_pr_title_and_comment_as_reason():
    msg = format_notification(
        "run_started",
        _data(
            run_kind="fix",
            issue_number="6",
            pr_number="12",
            pr_title="SAP-ORG-3.1 Organizasyonu adla değil kimlikle bul",
            title="[PR #12] İnceleme: PR #12\r\nBulgulari duzelt",
        ),
    )
    lines = msg.splitlines()
    assert lines[0] == "🔧 Düzeltme başladı · platform-reporting"
    assert lines[1] == "📌 PR #12 (Issue #6) — SAP-ORG-3.1 Organizasyonu adla değil kimlikle bul"
    assert lines[2] == "💬 Sebep: İnceleme: PR #12 Bulgulari duzelt"


def test_fix_run_without_pr_title_still_names_the_pr():
    msg = format_notification(
        "run_started", _data(run_kind="fix", issue_number="6", pr_number="12", title="[PR #12] x")
    )
    assert msg.splitlines()[1] == "📌 PR #12 (Issue #6)"


def test_failed_run_shows_error():
    msg = format_notification(
        "run_failed", _data(run_kind="fix", pr_number="12", error="Ajan CLI hata\nkoduyla bitti")
    )
    assert msg.startswith("❌ 🔧 Düzeltme başarısız · platform-reporting")
    assert "⚠️ Ajan CLI hata koduyla bitti" in msg


def test_events_without_run_kind_keep_the_old_format():
    msg = format_notification("run_started", {"run_id": 1, "title": "x", "project_id": "p"})
    assert msg.startswith("🚀 Run Started: p #1 — x")

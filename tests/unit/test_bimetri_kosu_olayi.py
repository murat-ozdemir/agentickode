# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: kosu olayi tipi, issue/PR'i, sunucuyu ve sonucu tasir (Slack bildirimi)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.worker.flow import executor
from backend.worker.flow._bimetri_olay import review_outcome, run_event_payload


def _kosu(**kw):
    alanlar = {
        "id": 153,
        "title": "[PR #11] Test: SAP-ORG-2.1 Kat değişiminde yeni organizasyon aç",
        "project_id": "bienport-iot-platform-reporting",
        "repo_name": "platform-reporting",
        "flow_prompt_id": 9,
        "task_source_meta": {"review_mode": "test", "issue_number": "5", "pr_number": "11"},
        "coding_results": {"agent": "claude", "model": "sonnet", "test_outcome": "Testler kaldı"},
        "review_result": None,
        "pr_url": "https://git.example/pulls/11",
        "workspace_server_id": 3,
        "started_at": datetime(2026, 11, 20, 15, 5, tzinfo=UTC),
        "completed_at": datetime(2026, 11, 20, 15, 9, 30, tzinfo=UTC),
    }
    return SimpleNamespace(**{**alanlar, **kw})


def _oturum(sunucu="worker-2"):
    return SimpleNamespace(commit=AsyncMock(), scalar=AsyncMock(return_value=sunucu))


async def test_test_kosusu_yuku_tip_sonuc_ve_sunucuyu_tasir():
    veri = await run_event_payload(_kosu(), _oturum())
    assert veri["run_kind"] == "test"
    assert veri["outcome"] == "Testler kaldı"
    assert veri["server"] == "worker-2"
    assert (veri["issue_number"], veri["pr_number"]) == ("5", "11")
    assert (veri["agent"], veri["model"]) == ("claude", "sonnet")
    assert veri["duration_seconds"] == 270
    assert veri["project_id"] == "bienport-iot-platform-reporting"


async def test_inceleme_sonucu_yorumun_sonundan_okunur():
    run = _kosu(
        task_source_meta={"review_mode": "comment", "pr_number": "11"},
        review_result={"summary": "...bulgular...\n\n**Karar:** Birleştirilebilir"},
    )
    veri = await run_event_payload(run, _oturum())
    assert veri["run_kind"] == "review"
    assert veri["outcome"] == "Birleştirilebilir"
    assert review_outcome("**Karar:** Değişiklik gerekli") == "Değişiklik gerekli"
    assert review_outcome("karar yok") is None


async def test_sunucu_okunamazsa_yuk_yine_olusur():
    oturum = _oturum()
    oturum.scalar = AsyncMock(side_effect=RuntimeError("db"))
    veri = await run_event_payload(_kosu(), oturum)
    assert veri["server"] is None


async def test_kod_kosusu_tipi_task():
    run = _kosu(task_source_meta={"issue_number": "5"}, coding_results=None, started_at=None)
    veri = await run_event_payload(run, _oturum())
    assert veri["run_kind"] == "task"
    assert veri["outcome"] is None
    assert veri["duration_seconds"] is None


async def test_akis_yoksa_hata_olayi_proje_ve_tipi_tasir():
    run = _kosu()
    with (
        patch.object(executor, "FlowPromptRepository") as repo,
        patch.object(executor.broadcaster, "event", new=AsyncMock()) as olay,
    ):
        repo.return_value.get_by_id = AsyncMock(return_value=None)
        await executor.execute_flow_prompt(run, _oturum(), None)
    ad, veri = olay.await_args.args[1:]
    assert ad == "run_failed"
    assert veri["project_id"] == "bienport-iot-platform-reporting"
    assert veri["run_kind"] == "test"
    assert run.status == "failed"

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: kosu bitis/hata olayi proje adini tasir (Slack bildirimi)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.services.notifications.formatter import format_notification
from backend.worker.flow import executor


def _kosu():
    return SimpleNamespace(
        id=63, title="ByteUtils", project_id="bienport-iot-platform-backend", flow_prompt_id=9
    )


def test_olay_yuku_proje_adini_tasir():
    assert executor._olay_yuku(_kosu()) == {
        "run_id": 63,
        "title": "ByteUtils",
        "project_id": "bienport-iot-platform-backend",
    }


def test_bitis_bildiriminde_proje_adi_var():
    veri = {**executor._olay_yuku(_kosu()), "status": "completed"}
    assert format_notification("run_completed", veri).startswith(
        "✅ Run Completed: bienport-iot-platform-backend #63 — ByteUtils"
    )


async def test_akis_yoksa_hata_olayi_proje_adini_tasir():
    run = _kosu()
    session = SimpleNamespace(commit=AsyncMock())
    with (
        patch.object(executor, "FlowPromptRepository") as repo,
        patch.object(executor.broadcaster, "event", new=AsyncMock()) as olay,
    ):
        repo.return_value.get_by_id = AsyncMock(return_value=None)
        await executor.execute_flow_prompt(run, session, None)
    ad, veri = olay.await_args.args[1:]
    assert ad == "run_failed"
    assert veri["project_id"] == "bienport-iot-platform-backend"
    assert run.status == "failed"

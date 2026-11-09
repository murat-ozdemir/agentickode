# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: merge edilen PR icin mem0 'ozellik_gecmisi' kaydi."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.api import _pr_webhook_helpers as yardimci
from backend.worker.flow import _bimetri_ozellik as ozellik
from tests.unit.bimetri_sahte import SahteGitea

PROJE = "Org/repo"
PR = {"number": 7, "title": " Modem ayrıştırıcı ", "merged_at": "2026-11-09T10:00:00+03:00"}


@pytest.fixture
def mem0_acik():
    with (
        patch.object(ozellik.settings, "mem0_url", "http://mem0:8000/"),
        patch.object(ozellik.settings, "mem0_api_key", "anahtar"),
    ):
        yield


def _yanit(veri, kod=200):
    return httpx.Response(kod, json=veri, request=httpx.Request("GET", "http://mem0"))


def _commit(konu, zaman):
    return {"created": zaman, "commit": {"message": f"{konu}\n\ngovde"}}


def _gitea():
    gp = SahteGitea()
    gp.yanitlar["/repos/org/repo/pulls/7/commits"] = (
        200,
        [_commit(f"c{i}", f"2026-11-0{i}T00:00:00Z") for i in range(1, 8)],
    )
    gp.dosya[7] = ["src/a/x.py", "src/a/y.py", "src/b/z.py", "README.md"]
    return gp


def _istemci(mevcut):
    client = MagicMock()
    client.get = AsyncMock(return_value=_yanit({"results": mevcut}))
    client.post = AsyncMock(return_value=_yanit({"results": []}))
    return client


class TestMetin:
    def test_matches_bootstrap_format_and_is_capped(self):
        metin = ozellik.ozellik_metni(3, "2026-11-09", "Baslik", ["a", "b"], ["src", "."])
        assert metin == "PR #3 (2026-11-09): Baslik. Commit'ler: a; b. Değişen yerler: src, .."
        assert len(ozellik.ozellik_metni(1, "t", "x" * 900, [], [])) == 800

    def test_newest_five_subjects_and_top_dirs(self):
        commitler = [_commit(f"c{i}", f"2026-11-0{i}T00:00:00Z") for i in range(1, 8)]
        assert ozellik.en_yeni_konular(commitler) == ["c7", "c6", "c5", "c4", "c3"]
        dosyalar = [{"filename": f} for f in _gitea().dosya[7]]
        assert ozellik.degisen_yerler(dosyalar)[:1] == ["src/a"]


class TestOzellikYaz:
    async def test_disabled_does_nothing(self):
        client = _istemci([])
        with (
            patch.object(ozellik.settings, "mem0_url", ""),
            patch.object(ozellik, "get_http_client", return_value=client),
        ):
            assert await ozellik.ozellik_yaz(_gitea(), PROJE, "org/repo", PR) == "kapali"
        client.get.assert_not_called()

    async def test_writes_record_without_inference(self, mem0_acik):
        client = _istemci([{"id": "1", "metadata": {"tur": "ozellik_gecmisi", "pr": 6}}])
        with patch.object(ozellik, "get_http_client", return_value=client):
            assert await ozellik.ozellik_yaz(_gitea(), PROJE, "org/repo", PR) == "yazildi"
        url = client.post.call_args.args[0]
        govde = client.post.call_args.kwargs["json"]
        assert url == "http://mem0:8000/memories"
        assert govde["user_id"] == PROJE and govde["infer"] is False
        assert govde["metadata"] == {
            "tur": "ozellik_gecmisi",
            "kaynak": "merge",
            "pr": 7,
            "tarih": "2026-11-09",
        }
        metin = govde["messages"][0]["content"]
        assert metin.startswith("PR #7 (2026-11-09): Modem ayrıştırıcı. Commit'ler: c7; c6;")
        assert "Değişen yerler: src/a, src/b, ." in metin

    async def test_skips_when_pr_already_recorded(self, mem0_acik):
        client = _istemci([{"id": "1", "metadata": {"tur": "ozellik_gecmisi", "pr": "7"}}])
        with patch.object(ozellik, "get_http_client", return_value=client):
            assert await ozellik.ozellik_yaz(_gitea(), PROJE, "org/repo", PR) == "var"
        client.post.assert_not_called()

    async def test_background_error_is_only_logged(self, mem0_acik, caplog):
        client = _istemci([])
        client.get = AsyncMock(return_value=_yanit({}, 401))
        with patch.object(ozellik, "get_http_client", return_value=client):
            ozellik.arka_planda_yaz(_gitea(), PROJE, "org/repo", PR)
            await asyncio.gather(*ozellik._gorevler)
        assert "PR #7 ozellik gecmisi yazilamadi" in caplog.text
        assert not ozellik._gorevler


class TestMergeWebhook:
    async def test_merge_schedules_record_with_project_name(self):
        proje = SimpleNamespace(
            project_id="p", repo_owner="Org", repo_name="repo", workspace_server_id=None
        )
        repo = MagicMock(get_by_git_repo=AsyncMock(return_value=proje))
        gp = MagicMock(set_status_label=AsyncMock())
        govde = {"pull_request": dict(PR, body=""), "repository": {"full_name": "org/repo"}}
        with (
            patch("backend.worker.phases._helpers.get_project_token", AsyncMock(return_value="t")),
            patch("backend.services.git.get_git_provider", return_value=gp),
            patch.object(ozellik, "arka_planda_yaz") as yaz,
            patch("backend.worker.flow._bimetri_proposals.schedule_proposals"),
        ):
            sonuc = await yardimci._bimetri_pr_merged(govde, MagicMock(), repo)
        assert sonuc == {"status": "accepted", "completed": [7]}
        yaz.assert_called_once_with(gp, PROJE, "org/repo", govde["pull_request"])

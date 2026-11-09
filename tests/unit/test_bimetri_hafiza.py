# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: kosu basinda mem0 proje hafizasi."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.worker.flow import _bimetri_hafiza as hafiza


@pytest.fixture
def mem0_acik():
    with (
        patch.object(hafiza.settings, "mem0_url", "http://mem0:8000/"),
        patch.object(hafiza.settings, "mem0_api_key", "anahtar"),
    ):
        yield


def _kayit(id_, memory, tur):
    return {"id": id_, "memory": memory, "score": 0.5, "metadata": {"tur": tur}}


def _istemci(*yanitlar):
    client = MagicMock()
    client.post = AsyncMock(side_effect=list(yanitlar))
    return client


def _yanit(results):
    return httpx.Response(200, json={"results": results}, request=httpx.Request("POST", "http://x"))


class TestHafizaEki:
    async def test_disabled_returns_empty_without_calling_mem0(self, make_task_run):
        client = _istemci()
        with patch.object(hafiza, "get_http_client", return_value=client):
            assert await hafiza.hafiza_eki(make_task_run()) == ""
        client.post.assert_not_called()

    async def test_project_records_first_then_related_without_duplicates(
        self, make_task_run, mem0_acik
    ):
        run = make_task_run(repo_owner="Bienport-IoT", repo_name="platform-backend")
        proje = _kayit("p1", "Spring Boot 3, Java 21.", "proje")
        client = _istemci(
            _yanit([proje]),
            _yanit([proje, _kayit("t1", "Testcontainers  için\nDocker gerekir.", "tuzak")]),
        )
        with patch.object(hafiza, "get_http_client", return_value=client):
            ek = await hafiza.hafiza_eki(run)

        assert "## Proje hafızası (mem0)" in ek
        assert ek.index("- [Proje] Spring Boot 3, Java 21.") < ek.index(
            "- [Tuzak] Testcontainers için Docker gerekir."
        )
        assert ek.count("Spring Boot 3") == 1
        ilk, ikinci = client.post.await_args_list
        assert ilk.args[0] == "http://mem0:8000/search"
        assert ilk.kwargs["headers"] == {"X-API-Key": "anahtar"}
        assert ilk.kwargs["json"]["filters"] == {
            "user_id": "Bienport-IoT/platform-backend",
            "tur": "proje",
        }
        assert ilk.kwargs["json"]["query"].startswith("Test task\nA test description")
        assert ikinci.kwargs["json"]["filters"] == {"user_id": "Bienport-IoT/platform-backend"}

    async def test_mem0_error_returns_empty_and_logs(self, make_task_run, mem0_acik):
        client = _istemci(httpx.ConnectError("baglanti yok"))
        log = AsyncMock()
        with (
            patch.object(hafiza, "get_http_client", return_value=client),
            patch("backend.worker.broadcaster.broadcaster.log", new=log),
        ):
            assert await hafiza.hafiza_eki(make_task_run()) == ""
        assert "Proje hafızası eklenmedi" in log.await_args.args[1]

    async def test_no_records_returns_empty(self, make_task_run, mem0_acik):
        client = _istemci(_yanit([]), _yanit([]))
        with patch.object(hafiza, "get_http_client", return_value=client):
            assert await hafiza.hafiza_eki(make_task_run()) == ""

    async def test_section_is_capped(self, make_task_run, mem0_acik):
        uzun = [_kayit(f"k{i}", "x" * 900, "ders") for i in range(8)]
        client = _istemci(_yanit([]), _yanit(uzun))
        with patch.object(hafiza, "get_http_client", return_value=client):
            ek = await hafiza.hafiza_eki(make_task_run())
        assert ek.count("- [Ders]") == 4
        assert len(ek) - len(hafiza._BASLIK) <= hafiza._BOLUM_SINIRI

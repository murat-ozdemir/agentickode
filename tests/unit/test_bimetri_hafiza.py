# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: project-memory section at run start."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services import bimetri_mem0
from backend.worker.flow import _bimetri_hafiza as memory

PROJECT = "Bienport-IoT/platform-backend"


@pytest.fixture
def mem0_on():
    with (
        patch.object(memory.settings, "mem0_url", "http://mem0:8000/"),
        patch.object(memory.settings, "mem0_api_key", "key"),
        patch.object(memory.settings, "bimetri_memory_mcp_token", ""),
    ):
        yield


def _record(id_, text, kind):
    return {"id": id_, "memory": text, "score": 0.5, "metadata": {"tur": kind}}


def _client(*responses):
    client = MagicMock()
    client.post = AsyncMock(side_effect=list(responses))
    return client


def _response(results):
    return httpx.Response(200, json={"results": results}, request=httpx.Request("POST", "http://x"))


def _run(make_task_run):
    return make_task_run(repo_owner="Bienport-IoT", repo_name="platform-backend")


class TestMemorySection:
    async def test_disabled_returns_empty_without_calling_mem0(self, make_task_run):
        client = _client()
        with patch.object(bimetri_mem0, "get_http_client", return_value=client):
            assert await memory.hafiza_eki(make_task_run()) == ""
        client.post.assert_not_called()

    async def test_project_then_knowledge_then_history_without_duplicates(
        self, make_task_run, mem0_on
    ):
        project = _record("p1", "Spring Boot 3, Java 21.", "proje")
        client = _client(
            _response([project]),
            _response([project, _record("t1", "Testcontainers  için\nDocker gerekir.", "tuzak")]),
            _response([_record("h1", "PR #12 added the parser.", "ozellik_gecmisi")]),
        )
        with patch.object(bimetri_mem0, "get_http_client", return_value=client):
            section = await memory.hafiza_eki(_run(make_task_run))

        assert "## Proje hafızası (mem0)" in section
        assert (
            section.index("- [Proje] Spring Boot 3")
            < section.index("- [Tuzak] Testcontainers için Docker gerekir.")
            < section.index("- [Özellik geçmişi] PR #12")
        )
        assert section.count("Spring Boot 3") == 1
        first, second, third = client.post.await_args_list
        assert first.args[0] == "http://mem0:8000/search"
        assert first.kwargs["headers"] == {"X-API-Key": "key"}
        assert first.kwargs["json"]["query"].startswith("Test task\nA test description")
        assert first.kwargs["json"]["filters"] == {"user_id": PROJECT, "tur": "proje"}
        assert first.kwargs["json"]["top_k"] == 3
        assert second.kwargs["json"]["filters"] == {
            "user_id": PROJECT,
            "tur": {"in": ["modul", "karar", "ders", "tuzak", "calisma"]},
        }
        assert second.kwargs["json"]["top_k"] == 8
        assert third.kwargs["json"]["filters"] == {"user_id": PROJECT, "tur": "ozellik_gecmisi"}
        assert third.kwargs["json"]["top_k"] == 3
        assert "search_project_memory" not in section

    async def test_mem0_error_returns_empty_and_logs(self, make_task_run, mem0_on):
        client = _client(httpx.ConnectError("no connection"))
        log = AsyncMock()
        with (
            patch.object(bimetri_mem0, "get_http_client", return_value=client),
            patch("backend.worker.broadcaster.broadcaster.log", new=log),
        ):
            assert await memory.hafiza_eki(make_task_run()) == ""
        assert "Proje hafızası eklenmedi" in log.await_args.args[1]

    async def test_no_records_returns_empty(self, make_task_run, mem0_on):
        client = _client(_response([]), _response([]), _response([]))
        with patch.object(bimetri_mem0, "get_http_client", return_value=client):
            assert await memory.hafiza_eki(make_task_run()) == ""

    async def test_tool_hint_shown_with_mcp_token_even_without_records(
        self, make_task_run, mem0_on
    ):
        run = _run(make_task_run)
        client = _client(_response([]), _response([]), _response([]))
        with (
            patch.object(bimetri_mem0, "get_http_client", return_value=client),
            patch.object(memory.settings, "bimetri_memory_mcp_token", "secret"),
        ):
            section = await memory.hafiza_eki(run)
        assert "`search_project_memory`" in section
        assert "`propose_memory`" in section
        assert f"`project` = `{PROJECT}`" in section
        assert f"`run_id` = {run.id}" in section
        assert "secret" not in section

    async def test_section_is_capped(self, make_task_run, mem0_on):
        long = [_record(f"k{i}", "x" * 900, "ders") for i in range(8)]
        client = _client(_response([]), _response(long), _response([]))
        with patch.object(bimetri_mem0, "get_http_client", return_value=client):
            section = await memory.hafiza_eki(make_task_run())
        assert section.count("- [Ders]") == 4
        assert len(section) - len(memory._HEADER) <= memory._SECTION_LIMIT

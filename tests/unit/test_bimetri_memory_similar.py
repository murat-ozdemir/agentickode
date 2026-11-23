# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: duplicate check for memory proposals (mem0 client + MCP helper)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

from backend.mcp import _bimetri_memory_similar as similar
from backend.services import bimetri_mem0

RID = "0b6f1b8e-2f53-4a4e-9c55-0f6f1a2b3c4d"


def _resp(status: int, body) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("GET", "http://mem0"))


def _hit(text: str, semantic: float, score: float = 0.4) -> dict:
    return {
        "id": text,
        "memory": text,
        "metadata": {"tur": "ders"},
        "score": score,
        "score_details": {"semantic_score": semantic},
    }


@pytest.fixture
def http():
    client = MagicMock()
    with (
        patch.object(bimetri_mem0, "get_http_client", return_value=client),
        patch.object(bimetri_mem0, "check_quota", AsyncMock()),
        patch.object(bimetri_mem0.settings, "mem0_url", "http://mem0/"),
    ):
        yield client


class TestMem0Client:
    async def test_similar_thresholds_on_semantic_score_not_combined_score(self, http):
        rows = [_hit("low", 0.41, score=0.9), _hit("close", 0.72), _hit("same", 0.91, score=0.46)]
        http.post = AsyncMock(return_value=_resp(200, {"results": rows}))
        found = await bimetri_mem0.similar_memories("o/r", "text", ("ders", "tuzak"), 0.6)
        assert [(r["id"], r["similarity"]) for r in found] == [("same", 0.91), ("close", 0.72)]
        body = http.post.call_args.kwargs["json"]
        assert body["explain"] is True
        assert body["filters"] == {"user_id": "o/r", "tur": {"in": ["ders", "tuzak"]}}

    async def test_get_returns_none_for_missing_record(self, http):
        http.get = AsyncMock(
            side_effect=[_resp(200, None), _resp(404, {}), _resp(200, {"id": "x"})]
        )
        assert await bimetri_mem0.get_memory("a") is None
        assert await bimetri_mem0.get_memory("b") is None
        assert await bimetri_mem0.get_memory("c") == {"id": "x"}

    async def test_update_puts_text_and_metadata(self, http):
        http.put = AsyncMock(return_value=_resp(200, {}))
        await bimetri_mem0.update_memory(RID, "new", {"tur": "ders"})
        assert http.put.call_args.args[0] == f"http://mem0/memories/{RID}"
        assert http.put.call_args.kwargs["json"] == {"text": "new", "metadata": {"tur": "ders"}}


class TestHelpers:
    async def test_find_similar_keeps_top_records_in_compact_form(self):
        rows = [_hit(f"r{i}", 0.9 - i / 100) | {"similarity": 0.9 - i / 100} for i in range(5)]
        with patch.object(similar, "similar_memories", AsyncMock(return_value=rows)) as search:
            found = await similar.find_similar("o/r", "text")
        assert search.call_args.args[3] == similar.MIN_SIMILARITY
        assert found is not None and len(found) == similar.MAX_SIMILAR
        assert found[0] == {"id": "r0", "text": "r0", "kind": "ders", "similarity": 0.9}

    async def test_find_similar_never_blocks_on_mem0_errors(self):
        failing = AsyncMock(side_effect=RuntimeError("down"))
        with patch.object(similar, "similar_memories", failing):
            assert await similar.find_similar("o/r", "text") is None

    async def test_replaced_record_must_belong_to_the_project(self):
        row = {"id": RID, "memory": "old", "user_id": "o/r", "metadata": {"tur": "karar"}}
        with patch.object(similar, "get_memory", AsyncMock(return_value=row)):
            assert await similar.replaced_record("o/r", RID) == {
                "id": RID,
                "text": "old",
                "kind": "karar",
            }
            with pytest.raises(ToolError, match="not a record of"):
                await similar.replaced_record("o/other", RID)
        with pytest.raises(ToolError, match="record id"):
            await similar.replaced_record("o/r", "PR #3")

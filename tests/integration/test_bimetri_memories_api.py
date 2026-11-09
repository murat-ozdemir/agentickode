# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""Integration tests for the bimetri read-only memories API."""

from unittest.mock import AsyncMock, patch

from backend.api import bimetri_memories as api

BASE = "/api/bimetri/memories"
ROWS = [
    {
        "id": "a",
        "memory": "Old module note",
        "metadata": {"tur": "modul", "kaynak": "seed"},
        "created_at": "2026-11-01T10:00:00+00:00",
    },
    {
        "id": "b",
        "memory": "Use ByteFifo.get()",
        "metadata": {"tur": "karar", "kaynak": "proposal", "pr": 49, "tarih": "2026-11-09"},
        "created_at": "2026-11-09T14:56:43+00:00",
    },
]


class TestMemoriesApi:
    async def test_lists_newest_first_with_english_fields(self, client):
        mock = AsyncMock(return_value=ROWS)
        with (
            patch.object(api, "mem0_enabled", return_value=True),
            patch.object(api, "list_memories", mock),
        ):
            resp = await client.get(BASE, params={"project": "Org/repo"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["kinds"] == ["karar", "modul"]
        data = body["items"]
        assert [r["id"] for r in data] == ["b", "a"]
        assert data[0] == {
            "id": "b",
            "text": "Use ByteFifo.get()",
            "kind": "karar",
            "source": "proposal",
            "pr_number": 49,
            "date": "2026-11-09",
            "created_at": "2026-11-09T14:56:43+00:00",
        }
        assert data[1]["pr_number"] is None
        mock.assert_awaited_once_with("Org/repo")

    async def test_filters_by_kind(self, client):
        with (
            patch.object(api, "mem0_enabled", return_value=True),
            patch.object(api, "list_memories", AsyncMock(return_value=ROWS)),
        ):
            resp = await client.get(BASE, params={"project": "Org/repo", "kind": "modul"})
        body = resp.json()
        assert [r["id"] for r in body["items"]] == ["a"]
        assert body["total"] == 1
        assert body["kinds"] == ["karar", "modul"]

    async def test_returns_the_requested_page(self, client):
        rows = [
            {"id": str(i), "memory": f"m{i}", "created_at": f"2026-11-{i + 1:02d}T00:00:00+00:00"}
            for i in range(5)
        ]
        with (
            patch.object(api, "mem0_enabled", return_value=True),
            patch.object(api, "list_memories", AsyncMock(return_value=rows)),
        ):
            resp = await client.get(BASE, params={"project": "Org/repo", "limit": 2, "offset": 2})
        body = resp.json()
        assert [r["id"] for r in body["items"]] == ["2", "1"]
        assert (body["total"], body["offset"], body["limit"]) == (5, 2, 2)

    async def test_rejects_limit_over_200(self, client):
        resp = await client.get(BASE, params={"project": "Org/repo", "limit": 201})
        assert resp.status_code == 422

    async def test_project_is_required(self, client):
        assert (await client.get(BASE)).status_code == 422

    async def test_503_when_mem0_disabled(self, client):
        with patch.object(api, "mem0_enabled", return_value=False):
            resp = await client.get(BASE, params={"project": "Org/repo"})
        assert resp.status_code == 503

    async def test_502_when_mem0_fails(self, client):
        with (
            patch.object(api, "mem0_enabled", return_value=True),
            patch.object(api, "list_memories", AsyncMock(side_effect=RuntimeError("down"))),
        ):
            resp = await client.get(BASE, params={"project": "Org/repo"})
        assert resp.status_code == 502
        assert "down" in resp.json()["detail"]

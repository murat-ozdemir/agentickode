# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""Integration tests for the bimetri memory-proposals API."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.api import bimetri_memory_proposals as api
from backend.models import MemoryProposal

BASE = "/api/bimetri/memory-proposals"


@pytest.fixture
async def proposal(db_session):
    row = MemoryProposal(project="Org/repo", pr_number=7, kind="lesson", text="Run ruff")
    other = MemoryProposal(project="Org/other", pr_number=2, kind="pitfall", text="x")
    db_session.add_all([row, other])
    await db_session.commit()
    return row


@pytest.fixture
def mem0_on():
    with (
        patch.object(api, "mem0_enabled", return_value=True),
        patch.object(api, "add_memory", AsyncMock(return_value="m-1")) as add,
    ):
        yield add


class TestMemoryProposalsApi:
    async def test_lists_with_filters(self, client, proposal):
        resp = await client.get(BASE, params={"status": "pending", "project": "Org/repo"})
        assert resp.status_code == 200
        assert [(p["id"], p["kind"]) for p in resp.json()] == [(proposal.id, "lesson")]
        assert len((await client.get(BASE)).json()) == 2
        assert (await client.get(BASE, params={"status": "bogus"})).status_code == 422

    async def test_edit_then_approve_writes_to_mem0(self, client, proposal, mem0_on):
        resp = await client.patch(
            f"{BASE}/{proposal.id}", json={"kind": "decision", "text": " Use uv "}
        )
        assert resp.status_code == 200 and resp.json()["text"] == "Use uv"
        resp = await client.post(f"{BASE}/{proposal.id}/approve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved" and data["mem0_id"] == "m-1"
        assert data["decided_at"]
        project, text, metadata = mem0_on.call_args.args
        assert (project, text) == ("Org/repo", "Use uv")
        assert metadata["tur"] == "karar" and metadata["pr"] == 7
        assert metadata["kaynak"] == "proposal"

    async def test_decided_proposal_cannot_change(self, client, proposal):
        assert (await client.post(f"{BASE}/{proposal.id}/reject")).json()["status"] == "rejected"
        assert (await client.post(f"{BASE}/{proposal.id}/approve")).status_code == 409
        resp = await client.patch(f"{BASE}/{proposal.id}", json={"text": "y"})
        assert resp.status_code == 409

    async def test_unknown_and_invalid_input(self, client, proposal):
        assert (await client.post(f"{BASE}/999/reject")).status_code == 404
        resp = await client.patch(f"{BASE}/{proposal.id}", json={"kind": "note"})
        assert resp.status_code == 422

    async def test_approve_needs_mem0(self, client, proposal):
        with patch.object(api, "mem0_enabled", return_value=False):
            assert (await client.post(f"{BASE}/{proposal.id}/approve")).status_code == 503

    async def test_mem0_failure_keeps_pending(self, client, proposal):
        with (
            patch.object(api, "mem0_enabled", return_value=True),
            patch.object(api, "add_memory", AsyncMock(side_effect=RuntimeError("down"))),
        ):
            assert (await client.post(f"{BASE}/{proposal.id}/approve")).status_code == 502
        resp = await client.get(BASE, params={"status": "pending", "project": "Org/repo"})
        assert len(resp.json()) == 1

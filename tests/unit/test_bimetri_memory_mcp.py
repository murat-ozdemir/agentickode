# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: project-memory MCP for agents (tools and bearer guard)."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import PlainTextResponse

from backend.mcp import bimetri_memory_server as server
from backend.mcp import bimetri_memory_tools as tools
from backend.repositories.memory_proposal_repo import MemoryProposalRepository

PROJECT = "org/repo"
pytestmark = pytest.mark.usefixtures("seed_proj1")


@pytest.fixture
def session_factory(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(tools, "async_session", factory):
        yield factory


@pytest.fixture
def mem0_on():
    with patch.object(tools, "mem0_enabled", return_value=True):
        yield


def _row(text, kind, created="2026-11-01T10:00:00+00:00", pr=None, score=None):
    meta = {"tur": kind, "kaynak": "seed"} | ({"pr": pr} if pr else {})
    return {"id": text, "memory": text, "metadata": meta, "created_at": created, "score": score}


class TestReadTools:
    async def test_search_uses_scope_kinds_and_returns_compact_records(
        self, session_factory, mem0_on
    ):
        search = AsyncMock(return_value=[_row("Use uv", "karar", pr=12, score=0.81234)])
        with patch.object(tools, "search_memories", search):
            found = await tools.search_project_memory(PROJECT, " uv? ", scope="history", limit=99)
        search.assert_awaited_once_with(PROJECT, "uv?", tools.HISTORY_KINDS, tools.MAX_LIMIT)
        assert found == [
            {
                "text": "Use uv",
                "kind": "karar",
                "source": "seed",
                "pr_number": 12,
                "created_at": "2026-11-01T10:00:00+00:00",
                "score": 0.812,
            }
        ]

    async def test_unregistered_or_malformed_project_is_refused(self, session_factory, mem0_on):
        for project in ("org/other", "org", "a/b/c"):
            with pytest.raises(ToolError):
                await tools.search_project_memory(project, "x")

    async def test_refused_while_mem0_is_off(self, session_factory):
        with patch.object(tools, "mem0_enabled", return_value=False), pytest.raises(ToolError):
            await tools.list_project_memory(PROJECT)

    async def test_list_filters_kind_newest_first(self, session_factory, mem0_on):
        rows = [
            _row("old", "tuzak", "2026-10-01T00:00:00+00:00"),
            _row("new", "tuzak", "2026-11-05T00:00:00+00:00"),
            _row("other", "karar"),
        ]
        with patch.object(tools, "list_memories", AsyncMock(return_value=rows)):
            listed = await tools.list_project_memory(PROJECT, kind="tuzak", limit=5)
        assert [r["text"] for r in listed] == ["new", "old"]
        with pytest.raises(ToolError, match="unknown kind"):
            await tools.list_project_memory(PROJECT, kind="secret")


class TestProposeMemory:
    async def test_stores_pending_agent_proposal_and_skips_duplicates(
        self, session_factory, db_session, make_task_run
    ):
        run = make_task_run()
        db_session.add(run)
        await db_session.commit()
        first = await tools.propose_memory(
            PROJECT, "pitfall", "Flyway needs\n the baseline.", run_id=run.id
        )
        again = await tools.propose_memory(PROJECT, "lesson", "Flyway needs the baseline.")
        assert first["status"] == "pending" and again["status"] == "duplicate"
        async with session_factory() as s:
            [row] = await MemoryProposalRepository(s).list_proposals(project=PROJECT)
        assert (row.source, row.run_id, row.pr_number, row.kind, row.status) == (
            "agent",
            run.id,
            None,
            "pitfall",
            "pending",
        )

    async def test_caps_proposals_per_run(self, session_factory, db_session, make_task_run):
        run = make_task_run()
        db_session.add(run)
        await db_session.commit()
        for i in range(tools.MAX_PROPOSALS_PER_RUN):
            await tools.propose_memory(PROJECT, "lesson", f"Lesson {i}", run_id=run.id)
        with pytest.raises(ToolError, match="per run"):
            await tools.propose_memory(PROJECT, "lesson", "One more", run_id=run.id)

    async def test_refuses_foreign_run_empty_text_and_unknown_project(
        self, session_factory, db_session, make_task_run
    ):
        run = make_task_run(repo_name="elsewhere")
        db_session.add(run)
        await db_session.commit()
        with pytest.raises(ToolError, match="does not belong"):
            await tools.propose_memory(PROJECT, "lesson", "x", run_id=run.id)
        with pytest.raises(ToolError, match="characters"):
            await tools.propose_memory(PROJECT, "lesson", "  ")
        with pytest.raises(ToolError, match="not a project"):
            await tools.propose_memory("org/unknown", "lesson", "x")
        async with session_factory() as s:
            assert await MemoryProposalRepository(s).list_proposals() == []


class TestServer:
    async def test_registers_the_three_tools(self):
        async with Client(server.mcp) as client:
            names = {t.name for t in await client.list_tools()}
        assert names == {"search_project_memory", "list_project_memory", "propose_memory"}

    @pytest.mark.parametrize(
        ("token", "header", "status"),
        [
            ("tok", "Bearer tok", 200),
            ("tok", "Bearer nope", 401),
            ("tok", None, 401),
            ("", "Bearer ", 401),
        ],
    )
    async def test_bearer_guard(self, token, header, status):
        guarded = server.BearerAuth(PlainTextResponse("inner"), token)
        headers = {"Authorization": header} if header else {}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=guarded), base_url="http://mcp"
        ) as client:
            assert (await client.post("/mcp", headers=headers)).status_code == status
            assert (await client.get("/health")).text == "ok"

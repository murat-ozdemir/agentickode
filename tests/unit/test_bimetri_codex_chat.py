# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: codex chat on ``codex exec --json``, and the chat 404 for a missing session."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.api.chat import get_session
from backend.models.chat import ChatSession
from backend.services.chat._bimetri_codex_chat import (
    BRIDGE,
    CodexEvents,
    codex_command,
    codex_message,
    needs_new_thread,
)
from backend.services.chat.chat_service import ChatService

THREAD = "019a0000-aaaa-7bbb-8ccc-000000000001"


def _lines(*events):
    return [json.dumps(e) for e in events]


RUN = _lines(
    {"type": "thread.started", "thread_id": THREAD},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"type": "error", "message": "Code Mode is unavailable"}},
    {"type": "item.started", "item": {"type": "mcp_tool_call", "tool": "list_projects"}},
    {"type": "item.completed", "item": {"type": "agent_message", "text": "3 proje var."}},
    {"type": "turn.completed", "usage": {}},
)


class TestCodexCommand:
    def test_new_thread_reads_stdin_with_the_platform_tools(self):
        cmd = codex_command("/tmp/m.txt", None, "http://localhost:8000")
        assert cmd.startswith("cat /tmp/m.txt | codex exec --json")
        assert cmd.endswith(" - 2>&1")
        assert "resume" not in cmd
        assert BRIDGE in cmd and "http://localhost:8000/mcp/sse" in cmd
        assert "read-only" in cmd
        assert "dangerously" not in cmd

    def test_later_messages_resume_the_thread(self):
        cmd = codex_command("/tmp/m.txt", THREAD, "http://localhost:8000")
        assert f"resume {THREAD} - 2>&1" in cmd

    def test_instructions_only_go_in_front_of_a_new_thread(self):
        assert codex_message("selam", "KURALLAR", True).startswith("KURALLAR")
        assert codex_message("selam", "KURALLAR", False) == "selam"

    def test_a_chat_needs_a_thread_until_codex_reported_one(self):
        assert needs_new_thread("codex", "chat-id", "chat-id")
        assert needs_new_thread("codex", None, "chat-id")
        assert not needs_new_thread("codex", THREAD, "chat-id")
        assert not needs_new_thread("claude", "chat-id", "chat-id")


class TestCodexEvents:
    def test_answer_tools_and_thread_id(self):
        events = CodexEvents()
        out = [t for line in RUN for t in events.feed(line)] + events.finish()
        assert out == ["\n[Using tool: list_projects]\n", "3 proje var."]
        assert events.thread_id == THREAD

    def test_failed_turn_shows_the_error_once(self):
        err = "unexpected status 401 Unauthorized"
        lines = _lines(
            {"type": "error", "message": f"Reconnecting... 1/5 ({err})"},
            {"type": "error", "message": err},
            {"type": "turn.failed", "error": {"message": err}},
        )
        assert CodexEvents().parse("\n".join(lines)) == f"[Codex hatası: {err}]"

    def test_log_lines_are_shown_only_when_there_is_no_answer(self):
        log = "2026-11-13T10:00:00Z ERROR codex_core: boom"
        assert CodexEvents().parse(log) == f"Codex yanıt vermedi:\n{log}"
        assert CodexEvents().parse("\n".join([log, *RUN])).endswith("3 proje var.")


class TestChatServiceThread:
    async def _chat(self, db):
        chat = ChatSession(session_id="c1", agent_name="codex", agent_session_id="c1", messages=[])
        db.add(chat)
        await db.commit()
        return chat

    async def test_streaming_keeps_the_thread_codex_started(self, db_session):
        chat = await self._chat(db_session)
        calls = []

        async def fake_stream(**kwargs):
            calls.append(kwargs)
            kwargs["session_sink"]["agent_session_id"] = THREAD
            yield "ok"

        with (
            patch("backend.services.chat.chat_service.invoke_agent_streaming", new=fake_stream),
            patch(
                "backend.services.chat.chat_service.get_platform_run_as_user",
                new=AsyncMock(return_value=None),
            ),
        ):
            for msg in ("bir", "iki"):
                async for _ in ChatService().send_message_streaming(db_session, "c1", msg):
                    pass

        assert chat.agent_session_id == THREAD
        assert calls[0]["is_new_session"] is True
        assert (calls[1]["is_new_session"], calls[1]["session_id"]) == (False, THREAD)


class TestChatGet404:
    async def test_unknown_session_is_404(self, db_engine):
        with (
            patch("backend.api.chat.async_session", async_sessionmaker(db_engine)),
            pytest.raises(HTTPException) as exc,
        ):
            await get_session("missing")
        assert exc.value.status_code == 404

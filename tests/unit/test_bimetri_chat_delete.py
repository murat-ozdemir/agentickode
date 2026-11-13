# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: deleting a chat session removes its row and the agent's transcript."""

import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from backend.api.local_terminals import close_local_session
from backend.models.chat import ChatSession
from backend.models.local_sessions import LocalTerminalSession
from backend.services.chat._bimetri_cleanup import remove_claude_session_files
from backend.services.chat.chat_service import ChatService

SID = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


def _claude_files(home, sid):
    root = home / ".claude"
    (root / "projects" / "-app").mkdir(parents=True, exist_ok=True)
    (root / "projects" / "-app" / f"{sid}.jsonl").write_text("{}")
    (root / "file-history" / sid).mkdir(parents=True)
    (root / "todos").mkdir(exist_ok=True)
    (root / "todos" / f"{sid}-agent-{sid}.json").write_text("[]")


class TestRemoveClaudeSessionFiles:
    def test_removes_only_that_session(self, tmp_path):
        _claude_files(tmp_path, SID)
        _claude_files(tmp_path, OTHER)

        removed = remove_claude_session_files(SID, tmp_path)

        assert len(removed) == 3
        left = sorted(p.name for p in (tmp_path / ".claude").rglob("*") if p.is_file())
        assert left == sorted([f"{OTHER}.jsonl", f"{OTHER}-agent-{OTHER}.json"])

    def test_rejects_a_non_uuid_id(self, tmp_path):
        _claude_files(tmp_path, SID)
        assert remove_claude_session_files("../*", tmp_path) == []
        assert remove_claude_session_files("*", tmp_path) == []
        assert (tmp_path / ".claude" / "projects" / "-app" / f"{SID}.jsonl").exists()


class TestDeleteSession:
    async def _add(self, db, agent="claude"):
        db.add(ChatSession(session_id=SID, agent_name=agent, agent_session_id=SID, messages=[]))
        await db.commit()

    async def test_deletes_the_row_and_the_transcript(self, db_session, tmp_path):
        await self._add(db_session)
        _claude_files(tmp_path, SID)
        with (
            patch(
                "backend.services.chat.chat_service.get_platform_run_as_user",
                new=AsyncMock(return_value=None),
            ),
            patch("backend.services.chat.chat_service.agent_home", return_value=tmp_path),
        ):
            assert await ChatService().delete_session(db_session, SID) is True

        rows = (await db_session.execute(select(ChatSession))).scalars().all()
        assert rows == []
        assert not list((tmp_path / ".claude").rglob(f"{SID}*"))

    async def test_deleted_session_is_not_listed(self, db_session, tmp_path):
        await self._add(db_session, agent="codex")
        with patch(
            "backend.services.chat.chat_service.get_platform_run_as_user",
            new=AsyncMock(return_value=None),
        ):
            await ChatService().delete_session(db_session, SID)
        assert await ChatService().list_sessions(db_session, "default") == []

    async def test_unknown_session_returns_false(self, db_session):
        assert await ChatService().delete_session(db_session, SID) is False


class TestTerminalDelete:
    async def test_deleting_a_terminal_also_removes_the_transcript(self, db_session, tmp_path):
        db_session.add(
            LocalTerminalSession(
                session_id="t1", agent_name="claude", tmux_name="lt-claude-t1", agent_session_id=SID
            )
        )
        await db_session.commit()
        _claude_files(tmp_path, SID)
        with (
            patch("backend.api.local_terminals.asyncio.create_subprocess_shell", new=AsyncMock()),
            patch("backend.api.local_terminals.broadcaster.office_event", new=AsyncMock()),
            patch("backend.api.local_terminals.agent_home", return_value=tmp_path),
        ):
            await close_local_session("t1", db_session)

        assert not list((tmp_path / ".claude").rglob(f"{SID}*"))

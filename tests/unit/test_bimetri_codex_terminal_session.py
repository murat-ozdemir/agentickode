# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a codex terminal session starts without ChatGPT-connected apps."""

from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from backend.models.local_sessions import LocalTerminalSession
from backend.services.workspace._bimetri_agent_launch import agent_launch_command
from backend.services.workspace.session_service import SessionService


async def test_codex_session_turns_off_chatgpt_apps():
    ssh = AsyncMock()
    ssh.run_command = AsyncMock(return_value=("123", "", 0))
    await SessionService(ssh).create_session("abcdef123456", "codex", "root", "/workspaces/a/b")
    sent = [c.args[0] for c in ssh.run_command.await_args_list if "send-keys" in c.args[0]]
    assert len(sent) == 1
    assert "'codex --no-daemon -c features.apps=false' Enter" in sent[0]


def test_local_terminals_launch_codex_without_apps():
    assert agent_launch_command("codex") == "codex --no-daemon -c features.apps=false"
    assert agent_launch_command("gemini") == "gemini"


async def test_creating_a_local_codex_terminal_sends_the_launch_line(client, db_session):
    proc = AsyncMock(returncode=0)
    with (
        patch("backend.api.local_terminals.get_platform_run_as_user", AsyncMock(return_value=None)),
        patch(
            "backend.api.local_terminals.asyncio.create_subprocess_shell",
            AsyncMock(return_value=proc),
        ) as shell,
    ):
        resp = await client.post("/api/local-terminals", json={"agent_name": "codex"})
    assert resp.status_code == 200
    sent = [c.args[0] for c in shell.await_args_list if "send-keys" in c.args[0]]
    assert sent and "'codex --no-daemon -c features.apps=false' Enter" in sent[0]
    stored = (await db_session.execute(select(LocalTerminalSession))).scalar_one()
    assert stored.last_command == "codex --no-daemon -c features.apps=false"  # used by resume

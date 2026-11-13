# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a codex terminal session starts without ChatGPT-connected apps."""

from unittest.mock import AsyncMock

from backend.services.workspace.session_service import SessionService


async def test_codex_session_turns_off_chatgpt_apps():
    ssh = AsyncMock()
    ssh.run_command = AsyncMock(return_value=("123", "", 0))
    await SessionService(ssh).create_session("abcdef123456", "codex", "root", "/workspaces/a/b")
    sent = [c.args[0] for c in ssh.run_command.await_args_list if "send-keys" in c.args[0]]
    assert len(sent) == 1
    assert "'codex -c features.apps=false' Enter" in sent[0]

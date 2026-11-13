# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: one turn per chat session, and a timed-out agent is really stopped."""

import asyncio
import os

from backend.services.chat._bimetri_chat_guard import (
    BUSY_DETAIL,
    kill_agent,
    session_turn,
    spawn_agent,
)


class TestSessionTurn:
    def test_second_turn_is_refused_while_first_runs(self):
        with session_turn("s1") as first:
            assert first
            with session_turn("s1") as second:
                assert not second
            with session_turn("s2") as other:
                assert other
        with session_turn("s1") as again:
            assert again

    async def test_message_endpoint_answers_409_while_busy(self, client):
        with session_turn("busy-session"):
            resp = await client.post(
                "/api/chat/sessions/busy-session/message", json={"message": "hadii"}
            )
        assert resp.status_code == 409
        assert resp.json()["detail"] == BUSY_DETAIL


class TestKillAgent:
    async def test_kills_the_command_behind_the_shell(self):
        # Like "cat msg | codex exec": the agent is a child of sh, not the shell itself.
        proc = await spawn_agent("sleep 30 | sleep 30", dict(os.environ))
        kill_agent(proc)
        await asyncio.wait_for(proc.wait(), timeout=5)
        for _ in range(50):
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                return
            await asyncio.sleep(0.05)
        raise AssertionError("agent process group still alive")

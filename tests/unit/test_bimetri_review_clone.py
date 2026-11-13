# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: the PR review agent runs inside the repo clone, on the PR branch."""

import shlex
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.adapters.cli_adapter import CLIAdapter
from backend.services.adapters.cli_wrappers import scope_generate
from backend.worker.flow._bimetri_review_clone import (
    REVIEW_ALLOWED_TOOLS,
    prepare_review_clone,
)
from backend.worker.steps.agent_step import _adapter_kwargs

GENERATE = "cat /tmp/p | claude --print --output-format json"


class TestScopeGenerate:
    def test_starts_in_the_clone_and_preapproves_tools(self):
        cmd = scope_generate(GENERATE, "/ws/my repo", ["mcp__bimetri-graph", "Bash(git log:*)"])
        assert cmd.startswith(f"cd {shlex.quote('/ws/my repo')} && cat /tmp/p | claude ")
        assert cmd.endswith("--allowedTools mcp__bimetri-graph 'Bash(git log:*)'")

    def test_unchanged_without_cwd_or_tools(self):
        assert scope_generate(GENERATE, None, None) == GENERATE

    def test_session_command_keeps_its_own_cd(self):
        cmd = "cd /w && cat /tmp/p | claude --print --resume s1"
        assert scope_generate(cmd, "/other", None) == cmd

    def test_tools_only_for_claude(self):
        assert scope_generate("codex --quiet -p /tmp/p", None, ["Read"]) == (
            "codex --quiet -p /tmp/p"
        )


class TestAdapterKwargs:
    def test_cwd_and_tools_passed_through(self):
        kwargs = _adapter_kwargs({"params": {"cwd": "/ws", "allowed_tools": ("Read",)}})
        assert kwargs["cwd"] == "/ws"
        assert kwargs["allowed_tools"] == ("Read",)

    def test_absent_when_not_given(self):
        kwargs = _adapter_kwargs({"params": {"prompt": "x"}})
        assert "cwd" not in kwargs
        assert "allowed_tools" not in kwargs


class TestGenerateCommand:
    async def test_cd_and_tools_end_up_inside_the_worker_user_shell(self):
        ssh = MagicMock()
        ssh.username = "root"
        ssh.run_command = AsyncMock(
            side_effect=[("/tmp/p\n", "", 0), ('{"result": "ok"}', "", 0), ("", "", 0)]
        )
        adapter = CLIAdapter(ssh_service=ssh, agent_name="claude", worker_user="coder")

        await adapter.generate("x", cwd="/ws", allowed_tools=REVIEW_ALLOWED_TOOLS)

        cmd = ssh.run_command.call_args_list[1].args[0]
        inner = shlex.split(cmd.split("runuser -u coder -- bash -c ", 1)[1])[0]
        assert "cd /ws && cat /tmp/p | claude --print" in inner
        assert "--allowedTools mcp__bimetri-graph Read" in inner


class TestPrepareReviewClone:
    async def test_runs_setup_and_init_and_returns_the_clone(self):
        run = SimpleNamespace(id=1, workspace_path="/ws/repo")
        run_phase = AsyncMock()

        assert await prepare_review_clone(run, None, None, run_phase) == "/ws/repo"  # type: ignore[arg-type]
        assert [c.args[0] for c in run_phase.call_args_list] == ["workspace_setup", "init"]

    async def test_setup_failure_falls_back_to_diff_only(self):
        run = SimpleNamespace(id=1, workspace_path="/ws/repo")
        run_phase = AsyncMock(side_effect=RuntimeError("clone failed"))

        with patch(
            "backend.worker.flow._bimetri_review_clone.broadcaster.log", new=AsyncMock()
        ) as log:
            assert await prepare_review_clone(run, None, None, run_phase) is None  # type: ignore[arg-type]
        assert "yalnızca diff" in log.call_args.args[1]
        assert log.call_args.kwargs["level"] == "warning"

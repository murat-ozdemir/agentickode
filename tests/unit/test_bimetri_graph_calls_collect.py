# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): graph call log of an agent call -> invocation metadata."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.worker.flow import _bimetri_graph_calls as gc


def _line(tool: str, returned: int, files: dict | None = None, **extra) -> str:
    return json.dumps(
        {"ts": 1.0, "tool": tool, "returned": returned, "files": files or {}, **extra}
    )


LOG = "\n".join(
    [
        _line("graph_continue", 400, {"a/A.java": 8000, "a/B.java": 4000}),
        _line("graph_read", 600, {"a/A.java": 8000}),
        _line("graph_callers", 300, {"a/B.java": 4000, "a/C.java": 2000}),
        _line("fallback_rg", 200, over=True),
        _line("graph_read", 30, error=True),
        "not json",
    ]
)


class TestSummarize:
    def test_counts_tools_and_estimates_savings_once_per_file(self):
        out = gc.summarize(LOG)
        assert out == {
            "calls": 5,
            "tools": {"graph_continue": 1, "graph_read": 2, "graph_callers": 1, "fallback_rg": 1},
            "errors": 1,
            "over_budget": 1,
            "files": 3,
            "returned_chars": 1530,
            "full_chars": 14000,
            "saved_tokens": (14000 - 1530) // 4,
        }

    def test_never_negative_and_none_without_calls(self):
        assert gc.summarize(_line("fallback_rg", 900))["saved_tokens"] == 0  # type: ignore[index]
        assert gc.summarize("") is None
        assert gc.summarize("garbage\n[]") is None


class TestCollect:
    def test_env_and_command_name_the_run(self):
        assert gc.run_env(266) == {"BIMETRI_RUN_ID": "266"}
        cmd = gc.collect_command(266)
        assert "/home/*/.local/share/bimetri-graph/calls/266.jsonl" in cmd
        assert 'rm -f "$f"' in cmd and cmd.endswith("; true")

    async def test_reads_the_log_over_ssh(self):
        ssh = SimpleNamespace(run_command=AsyncMock(return_value=(LOG, "", 0)))
        out = await gc.collect(SimpleNamespace(_ssh=ssh), 7)
        assert out is not None and out["calls"] == 5
        assert "calls/7.jsonl" in ssh.run_command.await_args.args[0]

    async def test_failure_or_no_ssh_gives_none(self):
        ssh = SimpleNamespace(run_command=AsyncMock(side_effect=OSError("down")))
        assert await gc.collect(SimpleNamespace(_ssh=ssh), 7) is None
        assert await gc.collect(SimpleNamespace(), 7) is None


class TestInvocationRecord:
    def test_graph_block_goes_to_metadata_even_when_the_call_failed(self):
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        from backend.worker.flow.executor import _bimetri_cagri_kaydi

        graph = gc.summarize(LOG)
        session = MagicMock()
        _bimetri_cagri_kaydi(
            MagicMock(id=1),
            session,
            "codex",
            "implement",
            datetime.now(UTC),
            {"graph": graph},
            RuntimeError("cli died"),
        )
        inv = session.add.call_args.args[0]
        assert inv.metadata_["graph"] == graph and inv.status == "failed"
        _bimetri_cagri_kaydi(
            MagicMock(id=1),
            session,
            "claude",
            "implement",
            datetime.now(UTC),
            {"graph": None},
            None,
        )
        assert "graph" not in session.add.call_args.args[0].metadata_

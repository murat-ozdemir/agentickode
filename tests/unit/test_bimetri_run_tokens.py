# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): per-call tokens and turns of the graph calls."""

import json
from unittest.mock import AsyncMock

from backend.services.adapters._bimetri_codex import parse_jsonl
from backend.services.adapters.cli_adapter import CLIAdapter
from backend.services.bimetri_run_tokens import TokenRow, build


class TestBuild:
    def test_averages_tokens_and_the_turns_of_calls_that_report_them(self):
        rows = [TokenRow(3_000_000, turns=40), TokenRow(1_000_001, turns=21), TokenRow(5)]
        out = build(rows)
        assert out["calls"] == 3 and out["tokens_per_call"] == 1_333_335
        assert out["turns_per_call"] == 30.5 and out["turn_calls"] == 2

    def test_no_calls_gives_no_averages(self):
        out = build([])
        assert out["calls"] == 0 and out["tokens_per_call"] is None
        assert out["turns_per_call"] is None and out["turn_calls"] == 0

    def test_shell_reads_are_summed_over_the_calls_that_report_them(self):
        rows = [TokenRow(9, shell_reads=3), TokenRow(9, shell_reads=0), TokenRow(9)]
        out = build(rows)
        assert out["shell_reads"] == 3 and out["shell_read_calls"] == 2


class TestClaudeUsage:
    def test_cache_split_and_turns_are_kept(self):
        adapter = CLIAdapter(AsyncMock(), "claude")
        usage = {
            "input_tokens": 30,
            "cache_creation_input_tokens": 1_000,
            "cache_read_input_tokens": 20_000,
            "output_tokens": 500,
        }
        out = {"result": "done", "usage": usage, "num_turns": 12, "total_cost_usd": 0.5}
        assert adapter._parse_json_output(json.dumps(out)) == "done"
        got = adapter._bimetri_usage
        assert got["input_tokens"] == 21_030 and got["turns"] == 12
        assert got["cache_read_input_tokens"] == 20_000
        assert got["cache_creation_input_tokens"] == 1_000

    def test_reaching_the_turn_cap_gives_a_readable_message(self):
        adapter = CLIAdapter(AsyncMock(), "claude")
        out = {"type": "result", "subtype": "error_max_turns", "num_turns": 81, "usage": {}}
        assert "81 tur" in adapter._parse_json_output(json.dumps(out))


class TestCodexShellReads:
    def test_counts_commands_that_print_a_source_file(self):
        commands = [
            "bash -lc \"sed -n '1,200p' core/src/A.java\"",
            "cat api/b.py",
            "rg -n update core",  # a search, not a read
            "cat README.md",
            "mvn -q test",
        ]
        items = [{"type": "command_execution", "command": c} for c in commands]
        events = [{"type": "item.completed", "item": i} for i in items]
        events.append({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})
        _message, usage = parse_jsonl("\n".join(json.dumps(e) for e in events))
        assert usage["shell_reads"] == 2 and usage["turns"] == 6

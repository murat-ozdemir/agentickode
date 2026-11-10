# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 2): the hook that keeps agents on the graph flow and its grep budget."""

import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _agent_graph_gate as gate_module  # noqa: E402

FIRST = gate_module.GATE_FIRST


def call(tmp_path, step, tool="Read", session="s1", **extra):
    event = {"session_id": session, "tool_name": tool, **extra}
    return gate_module.gate(step, json.dumps(event), tmp_path / "gate")


def mark(tmp_path, greps, session="s1"):
    reply = [{"type": "text", "text": json.dumps({"max_supplementary_greps": greps})}]
    return call(tmp_path, "mark", FIRST, session, tool_response=reply)


def bash(tmp_path, command):
    return call(tmp_path, "pre", "Bash", tool_input={"command": command})


class TestFirstCall:
    def test_pre_denies_until_graph_continue_is_marked(self, tmp_path, capsys):
        assert call(tmp_path, "pre", "Grep") == 2
        assert "graph_continue" in capsys.readouterr().err
        assert call(tmp_path, "pre", FIRST) == 0
        assert call(tmp_path, "pre", "ToolSearch") == 0
        assert mark(tmp_path, 1) == 0
        assert call(tmp_path, "pre", "Edit") == 0
        assert call(tmp_path, "pre", "Edit", session="other") == 2

    def test_session_id_cannot_leave_the_gate_dir(self, tmp_path):
        assert call(tmp_path, "mark", FIRST, session="../../x") == 0
        assert [p.name for p in (tmp_path / "gate").iterdir()] == ["x.ok"]


class TestBudget:
    def test_the_first_search_past_the_budget_is_denied_then_they_pass(self, tmp_path, capsys):
        mark(tmp_path, 2)
        assert call(tmp_path, "pre", "Grep") == 0
        assert bash(tmp_path, "rg -n update core/") == 0
        assert call(tmp_path, "pre", "Glob") == 2
        assert gate_module.GATE_SPENT in capsys.readouterr().err
        # Run #95: a hard stop made the agent give up on a complete caller list.
        assert call(tmp_path, "pre", "Glob") == 0
        assert bash(tmp_path, "grep -rn update .") == 0
        # Reading and editing go on; a new graph_continue gives a new budget.
        assert call(tmp_path, "pre", "mcp__bimetri-graph__graph_read") == 0
        assert bash(tmp_path, "mvn -q test") == 0
        mark(tmp_path, 1)
        assert call(tmp_path, "pre", "mcp__bimetri-graph__fallback_rg") == 0

    def test_unreadable_reply_gets_the_low_confidence_budget(self, tmp_path):
        call(tmp_path, "mark", FIRST, tool_response="Error: timeout")
        assert (tmp_path / "gate" / "s1.ok").read_text() == str(gate_module.DEFAULT_GREPS)

    def test_empty_marker_counts_as_the_default(self, tmp_path):
        (tmp_path / "gate").mkdir()
        (tmp_path / "gate" / "s1.ok").touch()
        assert call(tmp_path, "pre", "Grep") == 0
        assert (tmp_path / "gate" / "s1.ok").read_text() == str(gate_module.DEFAULT_GREPS - 1)


class TestSearches:
    @pytest.mark.parametrize(
        "command",
        [
            "grep -rn update .",
            "cd core && rg update",
            "LC_ALL=C /usr/bin/grep -r x src",
            "git grep -n ResourceStatusService",
            "find . -name '*.java' | xargs grep update",
            "ls; find src -name A.java",
            "echo $(rg -l x)",
        ],
    )
    def test_counts_search_commands(self, command):
        assert gate_module.searches(command)

    @pytest.mark.parametrize(
        "command",
        [
            "mvn -q test | grep FAIL",
            "git log --oneline | head",
            "sed -n 1,40p A.java",
            "git diff --stat",
            "",
        ],
    )
    def test_filters_and_other_commands_are_free(self, command):
        assert not gate_module.searches(command)

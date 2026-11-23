# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): graph calls' tokens against the pre-graph baseline."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from backend.services.adapters.cli_adapter import CLIAdapter
from backend.services.bimetri_run_tokens import TokenRow, build, task_key

T0 = datetime(2026, 11, 22, 12, tzinfo=UTC)


def _row(hours: float, tokens: int, graph: bool, **kw) -> TokenRow:
    base = {
        "repo": "platform-backend",
        "task_id": "pr-test-114",
        "agent": "codex",
        "phase": "implement",
        "turns": None,
    }
    return TokenRow(T0 + timedelta(hours=hours), tokens=tokens, graph=graph, **{**base, **kw})


class TestTaskKey:
    def test_review_comment_runs_of_a_pr_are_one_task(self):
        assert task_key("pr-comment-114-4734") == task_key("pr-comment-114-4791")
        assert task_key("pr-test-114") == "pr-test-114"
        assert task_key("94") == "94"


class TestBuild:
    def test_same_task_baseline_wins_over_the_repo_median(self):
        rows = [
            _row(-5, 6_000_000, False),
            _row(-4, 4_000_000, False),
            _row(-3, 100_000, False, task_id="other-1"),
            _row(-2, 100_000, False, task_id="other-2"),
            _row(1, 2_500_000, True, turns=40),
            _row(2, 2_500_000, True, turns=20),
        ]
        out = build(rows, None)
        assert out["compared"] == 2 and out["same_task"] == 2 and out["same_repo"] == 0
        assert out["baseline_tokens"] == 2 * 5_000_000 and out["actual_tokens"] == 5_000_000
        assert out["saved_pct"] == 50 and out["turns_per_call"] == 30

    def test_repo_median_needs_enough_samples_and_the_agent_and_phase(self):
        pre = [_row(-i, 1_000_000, False, task_id=f"t{i}") for i in (1, 2, 3)]
        rows = [
            *pre,
            _row(1, 3_000_000, True, task_id="new"),
            _row(1, 9, True, task_id="new", agent="claude"),
            _row(1, 9, True, task_id="new", phase="pr-review"),
        ]
        out = build(rows, None)
        assert out["graph_calls"] == 3 and out["compared"] == 1 and out["same_repo"] == 1
        assert out["saved_pct"] == -200  # signed: the graph call cost more
        assert build(rows[1:], None)["compared"] == 0  # two samples are not enough

    def test_only_calls_before_the_first_graph_call_count_and_since_filters(self):
        rows = [_row(-1, 1_000, False), _row(0, 500, True), _row(3, 9_000_000, False)]
        assert build(rows, None)["baseline_tokens"] == 1_000
        later = build(rows, T0 + timedelta(hours=1))
        assert later["graph_calls"] == 0 and later["saved_pct"] is None
        assert build([], None)["turns_per_call"] is None


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

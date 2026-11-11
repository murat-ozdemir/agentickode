# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Task Distribution card — classifier and aggregation."""

from datetime import date, datetime

from backend.services import bimetri_run_distribution as dist
from backend.services.bimetri_run_distribution import RunRow

TODAY = date(2026, 11, 11)


def _row(run_id, day=11, status="completed", meta=None, server="agent-1", calls=None):
    return RunRow(run_id, datetime(2026, 11, day, 9), status, meta or {}, server, calls or [])


class TestClassify:
    def test_reads_every_dimension(self):
        row = _row(
            1,
            meta={"labels": ["agent/codex", "difficulty/easy"], "review_mode": "test"},
            calls=[("codex", "gpt-6.1-terra"), ("claude", "claude-sonnet-5-5")],
        )
        assert dist.classify(row) == {
            "server": "agent-1",
            "agent": "codex",
            "model": "gpt-6.1-terra",
            "difficulty": "easy",
            "type": "test",
            "outcome": "completed",
        }

    def test_uses_sentinels_when_data_is_missing(self):
        cls = dist.classify(_row(1, server=None))
        assert cls["server"] == dist.NO_SERVER
        assert cls["agent"] == dist.NO_AGENT
        assert cls["model"] is None
        assert cls["difficulty"] == dist.NO_LABEL
        assert cls["type"] == "task"

    def test_model_unknown_when_call_has_no_model(self):
        assert dist.classify(_row(1, calls=[("claude", None)]))["model"] == dist.UNKNOWN_MODEL

    def test_maps_review_modes(self):
        types = [
            dist.classify(_row(1, meta={"review_mode": m}))["type"] for m in ("comment", "fix")
        ]
        assert types == ["review", "fix"]


class TestSinceFor:
    def test_ranges(self):
        assert dist.since_for("7d", TODAY) == date(2026, 11, 5)
        assert dist.since_for("30d", TODAY) == date(2026, 10, 13)
        assert dist.since_for("all", TODAY) is None


class TestBuild:
    def test_counts_days_and_groups(self):
        rows = [
            _row(1, day=9, calls=[("claude", "claude-sonnet-5-5")]),
            _row(2, day=11, status="failed", calls=[("codex", "gpt-6.1-terra")]),
            _row(3, day=11, calls=[("codex", "gpt-6.1-terra")]),
        ]
        out = dist.build(rows, None, TODAY)
        assert out["total"] == 3
        assert out["since"] == "2026-11-09"
        assert [d["total"] for d in out["days"]] == [1, 0, 2]
        assert out["days"][2]["by"]["agent"] == {"codex": 2}
        assert out["groups"]["agent"] == [
            {"name": "codex", "count": 2},
            {"name": "claude", "count": 1},
        ]

    def test_server_ok_pct_ignores_running(self):
        rows = [_row(1), _row(2, status="failed"), _row(3), _row(4, status="running")]
        server = dist.build(rows, None, TODAY)["groups"]["server"]
        assert server == [{"name": "agent-1", "count": 4, "ok_pct": 67}]

    def test_fixed_orders_keep_zero_values(self):
        out = dist.build([_row(1, meta={"labels": ["difficulty/hard"]})], None, TODAY)
        assert [i["name"] for i in out["groups"]["difficulty"]] == [
            "trivial",
            "easy",
            "medium",
            "hard",
        ]
        assert [i["count"] for i in out["groups"]["type"]] == [1, 0, 0, 0]

    def test_sentinels_sort_last(self):
        # two runs never called an agent, yet the real agent still comes first
        rows = [_row(1), _row(2), _row(3, calls=[("claude", None)])]
        agents = [i["name"] for i in dist.build(rows, None, TODAY)["groups"]["agent"]]
        assert agents == ["claude", dist.NO_AGENT]

    def test_range_starts_at_since(self):
        out = dist.build([_row(1)], date(2026, 11, 5), TODAY)
        assert len(out["days"]) == 7
        assert out["days"][-1]["total"] == 1

    def test_empty(self):
        out = dist.build([], None, TODAY)
        assert out["total"] == 0
        assert len(out["days"]) == 1


def test_matching_ids_follow_the_classifier():
    rows = [_row(1, calls=[("codex", "m")]), _row(2, calls=[("claude", "m")]), _row(3)]
    assert dist.matching_ids(rows, "agent", "codex") == [1]
    assert dist.matching_ids(rows, "agent", dist.NO_AGENT) == [3]
    assert dist.matching_ids(rows, "model", "m") == [1, 2]

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): Code graph card totals (services/bimetri_graph_usage.py)."""

from datetime import date, datetime

from backend.services import bimetri_graph_usage as gu


def _g(calls: int, saved: int, returned: int, full: int) -> dict:
    return {"calls": calls, "saved_tokens": saved, "returned_chars": returned, "full_chars": full}


TODAY = date(2026, 11, 22)
ROWS = [
    gu.GraphRow(1, datetime(2026, 11, 20, 9), "worker-1", [("claude", _g(4, 1000, 400, 4400))]),
    gu.GraphRow(
        2,
        datetime(2026, 11, 22, 9),
        "worker-2",
        [("claude", None), ("codex", _g(2, 500_000, 0, 2_000_000))],
    ),
    gu.GraphRow(3, datetime(2026, 11, 22, 10), None, [("claude", None)]),
    gu.GraphRow(4, datetime(2026, 11, 21, 10), "worker-1", []),
]


class TestBuild:
    def test_totals_count_only_runs_that_used_the_graph(self):
        out = gu.build(ROWS, date(2026, 11, 16), TODAY)
        assert out["total_runs"] == 4
        assert out["agents"] == {"claude": 1, "codex": 1}
        t = out["totals"]
        assert (t["runs"], t["calls"], t["saved_tokens"]) == (2, 6, 501_000)
        assert t["saved_usd"] == round(1000 * 3 / 1e6 + 500_000 * 2 / 1e6, 2)
        assert t["saved_pct"] == round(100 * (2_004_400 - 400) / 2_004_400)

    def test_days_cover_the_range_and_workers_sort_by_savings(self):
        out = gu.build(ROWS, date(2026, 11, 16), TODAY)
        assert len(out["days"]) == 7 and out["days"][-1] == {
            "date": "2026-11-22",
            "saved_tokens": 500_000,
        }
        assert [w["name"] for w in out["workers"]] == ["worker-2", "worker-1"]
        assert out["workers"][1]["saved_pct"] == 91

    def test_all_range_starts_at_the_first_graph_run(self):
        out = gu.build(ROWS, None, TODAY)
        assert out["since"] == "2026-11-20" and len(out["days"]) == 3
        assert gu.build([], None, TODAY)["totals"]["saved_pct"] is None

    def test_input_price_falls_back_by_agent_family(self):
        assert gu.input_price("ollama/qwen") == 0.0
        assert gu.input_price("unknown-agent") == 3.0

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (graf tasarruf planı, Faz 1): graph_read budget and dedupe per agent call."""

import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _graph_budget as budget  # noqa: E402
import _graph_flow_server as server  # noqa: E402

KEY = ("a.java", (1, 2))


class TestLedger:
    def test_every_answer_shows_what_is_left(self):
        ledger = budget.Ledger(limit=100)
        assert ledger.repeat("a.java", KEY, [(1, 3)]) is None
        assert ledger.send("x" * 40, KEY, [(1, 3)]).endswith(
            "\n[graph budget: 60 of 100 characters left]"
        )

    def test_large_answers_stop_at_the_limit_small_ones_still_pass(self, monkeypatch):
        monkeypatch.setattr(budget, "SMALL_CHARS", 10)
        ledger = budget.Ledger(limit=100)
        ledger.send("x" * 95, KEY, [(1, 3)])
        assert ledger.send("y" * 20, KEY, [(4, 9)]).startswith("budget_exhausted: ")
        assert ledger.send("z" * 8, KEY, [(4, 5)]).startswith("z" * 8 + "\n[graph budget: 0 of")

    def test_lines_already_sent_get_a_note_once_then_are_served(self):
        ledger = budget.Ledger()
        ledger.repeat("a.java", KEY, None)
        ledger.send("text", KEY, [(1, 20)])
        note = ledger.repeat("a.java::update", KEY, [(5, 9)])
        assert note and note.startswith("a.java::update: already sent by graph call #1")
        assert ledger.repeat("a.java::update", KEY, [(5, 9)]) is None
        assert ledger.repeat("a.java:15-25", KEY, [(15, 25)]) is None  # lines 21-25 are new

    def test_a_changed_file_is_a_new_key(self):
        ledger = budget.Ledger()
        ledger.send("text", KEY, [(1, 20)])
        assert ledger.repeat("a.java", ("a.java", (3, 4)), [(1, 20)]) is None

    def test_request_keys_without_ranges(self):
        ledger = budget.Ledger()
        ledger.repeat("update", ("callers", "update"))
        ledger.send("callers", ("callers", "update"))
        assert "graph call #1" in ledger.repeat("update", ("callers", "update"))


class TestServer:
    def test_graph_read_dedupes_and_counts_the_run(self, tmp_path):
        (tmp_path / "A.java").write_text("class A {\n  void run() {}\n}\n")
        made = server.Flow(tmp_path / "graph.json", tmp_path, None, None)
        first, error = made.call("graph_read", {"file": "A.java"})
        assert not error and first.startswith("1: class A {")
        assert (
            "already sent by graph call #1" in made.call("graph_read", {"file": "A.java::run"})[0]
        )
        assert made.call("graph_read", {"file": "A.java::run"})[0].startswith("A.java:2-2")
        assert made.ledger.calls == 3

    def test_errors_cost_nothing(self, tmp_path):
        made = server.Flow(tmp_path / "graph.json", tmp_path, None, None)
        assert made.call("graph_read", {"file": "nope.java"})[0].startswith("no such file")
        assert made.ledger.used == 0

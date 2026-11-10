# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 2): graph_continue flow over the Graphify graph (no networkx here)."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _graph_flow as flow  # noqa: E402
import _graph_flow_server as server  # noqa: E402

SVC = "core/src/ResourceStatusService.java"
JAVA = """package x;

public class ResourceStatusService {
    /* a { brace in a comment,
     * and void update(int x) in a Javadoc */
    private final String s = "}";

    public void update(String id) {
        if (id != null) {
            save(id);
        }
    }

    abstract void close();

    void other() { return update("a"); }
}
"""


class _Nodes(dict):
    def __call__(self, data=False):
        return list(self.items())


class FakeGraph:  # the slice of networkx.DiGraph the flow uses
    def __init__(self, nodes: dict, links: list) -> None:
        self.nodes, self._links, self.graph = _Nodes(nodes), links, {"built_at_commit": "abc"}

    def in_edges(self, nid, data=False):
        return [(s, t, d) for s, t, d in self._links if t == nid]


def node(label, source, line=1):
    return dict(label=label, source_file=source, source_location=f"L{line}", file_type="code")


@pytest.fixture
def fake():
    nodes = {
        "svc": node("ResourceStatusService", SVC, 3),
        "upd": node(".update()", SVC, 7),
        "ctl": node(".refresh()", "api/StatusController.java", 20),
        "job": node(".run()", "jobs/StatusJob.java", 9),
        "file": node("StatusJob.java", "jobs/StatusJob.java"),
        "doc": {**node("update", "README.md"), "file_type": "document"},
    }
    links = [
        ("ctl", "upd", {"relation": "calls", "source_location": "L57"}),
        ("job", "upd", {"relation": "calls", "source_location": "L12"}),
        ("file", "svc", {"relation": "imports", "source_location": "L3"}),
        ("svc", "upd", {"relation": "method", "source_location": "L7"}),
    ]
    return FakeGraph(nodes, links)


class TestContinue:
    def test_named_symbols_and_their_users_with_reasons(self, fake, tmp_path):
        result = flow.continue_flow(
            fake, "ResourceStatusService.update() içinde null kontrolü", tmp_path
        )
        assert result["confidence"] == "high"
        # Callers of the named method come before the users of its class.
        assert result["recommended_files"][2] == "api/StatusController.java::refresh"
        assert result["recommended_files"][:2] == [SVC, f"{SVC}::update"]
        assert result["why"]["api/StatusController.java::refresh"] == "calls .update() at L57"
        # The file node and the class named after its file both read as the bare path.
        assert result["why"]["jobs/StatusJob.java"].startswith("imports ResourceStatusService")
        assert (result["max_supplementary_greps"], result["max_supplementary_files"]) == (1, 2)

    def test_names_missing_from_the_graph_lower_confidence(self, fake, tmp_path):
        result = flow.continue_flow(fake, "DeviceGateway ve ResourceStatusService", tmp_path)
        assert result["confidence"] == "medium" and result["not_in_graph"] == ["DeviceGateway"]

    def test_falls_back_to_graphify_scoring_when_nothing_is_named(self, fake, tmp_path):
        result = flow.continue_flow(fake, "durum servisi", tmp_path, lambda task: ["ctl", "job"])
        assert result["confidence"] == "low" and result["max_supplementary_greps"] == 4
        assert result["recommended_files"][0] == "api/StatusController.java::refresh"

    def test_paths_named_in_the_task_are_recommended_if_present(self, fake, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "B.java").write_text("")
        result = flow.continue_flow(fake, "a/B.java ve yok/C.java düzelt", tmp_path)
        assert result["recommended_files"] == ["a/B.java"]

    def test_caps_the_list_and_points_at_graph_callers(self, fake, tmp_path, monkeypatch):
        monkeypatch.setattr(flow, "MAX_RECOMMENDED", 2)
        result = flow.continue_flow(fake, "update()", tmp_path)
        assert len(result["recommended_files"]) == 2 and result["more_users"].startswith("1 more")


class TestRead:
    @pytest.fixture
    def root(self, tmp_path):
        (tmp_path / "core/src").mkdir(parents=True)
        (tmp_path / SVC).write_text(JAVA)
        return tmp_path

    def test_symbol_reads_only_its_block(self, root):
        text = flow.read(root, f"{SVC}::update")
        assert text.splitlines()[0] == f"{SVC}:8-12"
        assert text.splitlines()[-1] == "12:     }"

    def test_declarations_skip_calls_and_comments(self):
        lines = JAVA.splitlines()
        assert [lines[i].strip()[:20] for i in flow.declarations(lines, "update")] == [
            "public void update(S"
        ]

    def test_body_less_declaration_ends_at_its_semicolon(self, root):
        assert flow.read(root, f"{SVC}::close").splitlines()[0] == f"{SVC}:14-14"

    def test_class_block_ignores_braces_in_strings_and_comments(self, root):
        assert flow.read(root, f"{SVC}::ResourceStatusService").splitlines()[0] == f"{SVC}:3-17"

    def test_whole_file_is_capped(self, root, monkeypatch):
        monkeypatch.setattr(flow, "FILE_LINES", 2)
        assert flow.read(root, SVC).splitlines() == [
            "1: package x;",
            "2: ",
            "... 15 more lines; read a symbol with file::Name",
        ]

    def test_stays_inside_the_clone(self, root):
        assert flow.read(root, "../etc/passwd").startswith("no such file")
        assert "not declared" in flow.read(root, f"{SVC}::missing")


class TestCallersAndRg:
    def test_callers_list_use_sites(self, fake):
        assert flow.callers(fake, "update()").splitlines() == [
            "api/StatusController.java:57 .refresh() calls .update()",
            "jobs/StatusJob.java:12 .run() calls .update()",
        ]
        assert flow.callers(fake, "Nope") == "Nope is not in the graph"

    def test_rg_output_is_capped(self, monkeypatch, tmp_path):
        out = SimpleNamespace(stdout="a:1:x\n" * 5, stderr="")
        calls = []
        monkeypatch.setattr(server.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or out)
        monkeypatch.setattr(server, "OUTPUT_LINES", 3)
        assert server.rg(tmp_path, "-rf", "*.java").splitlines()[-1] == "... 2 more lines"
        # The pattern always goes behind -e, so it is never read as an option.
        assert calls[0][-5:] == ["-e", "-rf", "-g", "*.java", "."]


class TestServerFlow:
    def make(self, fake, tmp_path):
        graph = tmp_path / "graph.json"
        graph.write_text("{}")
        loads = []
        made = server.Flow(graph, tmp_path, lambda p: loads.append(p) or fake, lambda fake, t: [])
        return made, loads

    def test_fallback_rg_needs_graph_continue_and_keeps_to_its_budget(
        self, fake, tmp_path, monkeypatch
    ):
        made, _ = self.make(fake, tmp_path)
        monkeypatch.setattr(server, "rg", lambda root, pattern, glob: f"hit {pattern}")
        assert made.call("fallback_rg", {"pattern": "x"}) == ("call graph_continue first", True)
        text, error = made.call("graph_continue", {"task": "update()"})
        assert not error and json.loads(text)["graph_commit"] == "abc"
        assert made.call("fallback_rg", {"pattern": "x"}) == ("hit x", False)
        assert "budget used up" in made.call("fallback_rg", {"pattern": "y"})[0]

    def test_missing_argument_is_an_error(self, fake, tmp_path):
        made, _ = self.make(fake, tmp_path)
        assert made.call("graph_read", {}) == ("graph_read needs `file`", True)

    def test_graph_is_reloaded_only_when_the_file_changes(self, fake, tmp_path):
        made, loads = self.make(fake, tmp_path)
        made.graph()
        made.graph()
        assert len(loads) == 1
        made.stamp = -1  # graph.json written since
        made.graph()
        assert len(loads) == 2

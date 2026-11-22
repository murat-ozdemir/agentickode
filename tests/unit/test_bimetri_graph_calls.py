# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): per-run log of graph tool calls (_graph_calls.py)."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _graph_calls as calls  # noqa: E402
import _graph_flow_server as server  # noqa: E402


def _proc(tmp_path: Path, pid: int, ppid: int, env: dict) -> None:
    d = tmp_path / str(pid)
    d.mkdir()
    (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in env.items()))
    (d / "stat").write_text(f"{pid} (co de) S {ppid} 1 1")


class TestRunId:
    def test_own_environment_wins(self, tmp_path):
        assert calls.run_id({"BIMETRI_RUN_ID": "42"}, tmp_path, 7) == "42"

    def test_found_in_an_ancestor_when_codex_drops_it(self, tmp_path):
        _proc(tmp_path, 30, 20, {"PATH": "/bin"})  # the codex process' MCP launcher
        _proc(tmp_path, 20, 10, {"BIMETRI_RUN_ID": "266", "HOME": "/home/coder"})
        assert calls.run_id({}, tmp_path, 30) == "266"

    def test_none_without_a_numeric_id(self, tmp_path):
        _proc(tmp_path, 30, 1, {"BIMETRI_RUN_ID": "x"})
        assert calls.run_id({}, tmp_path, 30) is None
        assert calls.run_id({}, tmp_path, 99) is None  # no such process


class TestPointedAt:
    def test_graph_read_strips_symbol_and_line(self):
        assert calls.pointed_at("graph_read", {"file": "a/B.java::run"}, "") == ["a/B.java"]
        assert calls.pointed_at("graph_read", {"file": "a/B.java:10-20"}, "") == ["a/B.java"]

    def test_callers_and_continue(self):
        text = "a/X.java:12 X calls run: run();\na/Y.java:3 Y calls run"
        assert calls.pointed_at("graph_callers", {}, text) == ["a/X.java", "a/Y.java"]
        rec = json.dumps({"recommended_files": ["a/X.java::run", "a/Y.java:3", "b.py"]})
        assert calls.pointed_at("graph_continue", {}, rec) == ["a/X.java", "a/Y.java", "b.py"]
        assert calls.pointed_at("graph_continue", {}, "not json") == []
        assert calls.pointed_at("fallback_rg", {"pattern": "x"}, "a/X.java:1:x") == []


class TestRecorder:
    def test_appends_a_line_per_call_with_file_sizes(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        (root / "A.java").write_text("x" * 1000)
        rec = calls.Recorder(root.resolve(), "7", tmp_path / "calls")
        rec("graph_read", {"file": "A.java::run"}, "abc", False)
        rec("fallback_rg", {"pattern": "p"}, "A.java:1:x\n(over graph_continue's max_s)", False)
        rec("graph_read", {"file": "../outside"}, "no such file", False)
        lines = [json.loads(x) for x in (tmp_path / "calls" / "7.jsonl").read_text().splitlines()]
        assert [x["tool"] for x in lines] == ["graph_read", "fallback_rg", "graph_read"]
        assert lines[0]["returned"] == 3 and lines[0]["files"] == {"A.java": 1000}
        assert lines[1]["over"] is True and lines[1]["files"] == {}
        assert lines[2]["files"] == {}

    def test_no_run_id_writes_nothing(self, tmp_path):
        calls.Recorder(tmp_path, None, tmp_path / "calls")("graph_read", {}, "x", False)
        assert not (tmp_path / "calls").exists()

    def test_server_records_every_call_even_a_failing_one(self, monkeypatch):
        seen, made = [], {}

        class Server:  # stands in for mcp.server.Server: keeps the handlers
            def __init__(self, name, **handlers):
                made.update(handlers)

        types = SimpleNamespace(
            Tool=dict, TextContent=dict, CallToolResult=dict, ListToolsResult=dict
        )
        monkeypatch.setitem(sys.modules, "mcp", SimpleNamespace(types=types))
        monkeypatch.setitem(sys.modules, "mcp.server", SimpleNamespace(Server=Server))

        class Boom:
            def call(self, name, args):
                raise RuntimeError("no graph")

        server.build_server(Boom(), lambda *a: seen.append(a))  # type: ignore[arg-type]
        params = SimpleNamespace(name="graph_callers", arguments={"symbol": "run"})
        result = asyncio.run(made["on_call_tool"](None, params))
        assert result["isError"] is True
        assert seen == [
            ("graph_callers", {"symbol": "run"}, "graph_callers failed: no graph", True)
        ]

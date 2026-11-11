# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 1-2): local code graph MCP setup on the workers."""

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _agent_graph_config as config  # noqa: E402
import _agent_graph_mcp as graph  # noqa: E402
import _graph_flow as flow  # noqa: E402
import _graph_flow_server as server  # noqa: E402

ROOT = Path("/workspaces/Org/repo")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "home", lambda: tmp_path)
    monkeypatch.setattr(graph, "home", lambda: tmp_path)
    return tmp_path


class TestPaths:
    def test_data_dir_is_outside_the_clone(self, home):
        data = graph.data_dir("graphify", ROOT)
        assert data == home / ".local/share/bimetri-graph/data/graphify/workspaces__Org__repo"

    def test_tool_env_points_graphify_at_its_data_dir(self, home):
        data = str(graph.data_dir("graphify", ROOT))
        env = graph.tool_env("graphify", ROOT)
        assert env["GRAPHIFY_OUT"] == data
        assert env["GRAPHIFY_QUERY_LOG_DISABLE"] == "1"

    def test_commands_use_the_tool_venv(self, home):
        venv = home / ".local/share/bimetri-graph"
        assert graph.update_command("graphify", ROOT) == [
            str(venv / "graphify/bin/graphify"),
            "update",
            str(ROOT),
        ]
        # The flow server runs isolated on the graph and the clone.
        assert graph.server_command("graphify", ROOT) == [
            str(venv / "graphify/bin/python"),
            "-I",
            str(venv / "graph_flow.py"),
            str(graph.data_dir("graphify", ROOT) / "graph.json"),
            str(ROOT),
        ]


class TestInstallBundle:
    def test_split_bundle_separates_source_locks_and_files(self):
        source, locks, files = graph.split_bundle(
            "print(1)\n### lock: graphify\na==1\n### file: graph_flow.py\n### x\nb = 2\n"
        )
        assert source == "print(1)\n"
        assert locks == {"graphify": "a==1\n"}
        # A "### " line that is no part marker stays in the part.
        assert files == {"graph_flow.py": "### x\nb = 2\n"}

    def test_install_refuses_a_missing_lock_or_flow_server(self, home, capsys):
        assert graph.install("print(1)\n### lock: graphify\na==1\n") == 1
        assert "graph_flow.py" in capsys.readouterr().err
        assert graph.install("print(1)\n### file: graph_flow.py\nx = 1\n") == 1
        assert "lock graphify" in capsys.readouterr().err
        assert not (home / ".local").exists()


class TestUpdateAndServe:
    def test_clean_head_is_none_for_a_changed_tree(self, monkeypatch):
        replies = iter([SimpleNamespace(returncode=0, stdout=" M a.py\n")])
        monkeypatch.setattr(graph.subprocess, "run", lambda *a, **kw: next(replies))
        assert graph.clean_head(ROOT) is None
        replies = iter([SimpleNamespace(returncode=0, stdout=""), SimpleNamespace(stdout="abc\n")])
        assert graph.clean_head(ROOT) == "abc"

    def fake_update(self, monkeypatch, rc, head):
        calls = []
        monkeypatch.setattr(graph, "clean_head", lambda root: head)
        monkeypatch.setattr(
            graph.subprocess,
            "run",
            lambda cmd, **kw: calls.append((cmd, kw)) or SimpleNamespace(returncode=rc),
        )
        return calls

    def test_update_reports_rc_and_time(self, home, monkeypatch, capsys):
        calls = self.fake_update(monkeypatch, 3, "abc")
        assert graph.update("graphify", ROOT) == 3
        assert calls[0][1]["cwd"] == ROOT and calls[0][1]["stdout"] == 2
        assert capsys.readouterr().out.startswith("graphify: update rc=3 in ")
        assert graph.built_at("graphify", ROOT).read_text() == ""

    def test_update_of_a_clean_tree_stamps_its_head(self, home, monkeypatch):
        self.fake_update(monkeypatch, 0, "abc")
        graph.update("graphify", ROOT)
        assert graph.built_at("graphify", ROOT).read_text() == "abc"
        self.fake_update(monkeypatch, 0, None)
        graph.update("graphify", ROOT)
        assert graph.built_at("graphify", ROOT).read_text() == ""

    def test_serve_outside_git_fails(self, home, monkeypatch, capsys):
        monkeypatch.setattr(
            graph.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=128, stdout="")
        )
        assert graph.serve("graphify") == 1
        assert "not inside a git clone" in capsys.readouterr().err

    def test_hung_update_times_out_and_stamps_nothing(self, home, monkeypatch, capsys):
        monkeypatch.setattr(graph, "clean_head", lambda root: "abc")

        def hang(cmd, **kw):
            raise graph.subprocess.TimeoutExpired(cmd, kw["timeout"])

        monkeypatch.setattr(graph.subprocess, "run", hang)
        assert graph.update("graphify", ROOT) == 124
        assert graph.built_at("graphify", ROOT).read_text() == ""

    def test_background_update_runs_in_its_own_session(self, home, monkeypatch, capsys):
        started = []
        monkeypatch.setattr(graph.subprocess, "Popen", lambda cmd, **kw: started.append((cmd, kw)))
        graph.update_in_background("graphify", ROOT)
        cmd, kw = started[0]
        assert cmd[1:] == [
            str(graph.base_dir() / "agent_graph.py"),
            "update",
            "graphify",
            str(ROOT),
        ]
        assert kw["start_new_session"] and kw["stdin"] == graph.subprocess.DEVNULL
        assert kw["stdout"].name.endswith(".log")  # not serve's stderr, which the CLI may close
        assert "in the background" in capsys.readouterr().err

    def test_background_update_is_skipped_while_one_runs(self, home, monkeypatch, capsys):
        started = []
        monkeypatch.setattr(graph.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
        graph.data_dir("graphify", ROOT).mkdir(parents=True)
        with open(graph.lock_path("graphify", ROOT), "w") as held:
            graph.fcntl.flock(held, graph.fcntl.LOCK_EX)
            graph.update_in_background("graphify", ROOT)
        assert started == []
        assert "already running" in capsys.readouterr().err

    def serve(self, monkeypatch, head=None):
        git = SimpleNamespace(returncode=0, stdout=f"{ROOT}\n")
        monkeypatch.setattr(graph.subprocess, "run", lambda *a, **kw: git)
        monkeypatch.setattr(graph, "clean_head", lambda root: head)
        built, execs = [], []
        monkeypatch.setattr(graph, "update_in_background", lambda tool, root: built.append(root))
        monkeypatch.setattr(graph.os, "execve", lambda *args: execs.append(args))
        return graph.serve("graphify"), built, execs

    def test_serve_starts_the_update_and_execs_at_once(self, home, monkeypatch, capsys):
        _, built, execs = self.serve(monkeypatch)  # no graph yet: the server still starts
        assert built == [ROOT]
        assert execs[0][1] == graph.server_command("graphify", ROOT)
        assert execs[0][2]["GRAPHIFY_OUT"] == str(graph.data_dir("graphify", ROOT))
        assert capsys.readouterr().out == ""  # stdout belongs to MCP

    def test_before_the_first_build_graph_continue_opens_with_low_caps(self, tmp_path):
        made = server.Flow(tmp_path / "graph.json", tmp_path, None, None)
        result = json.loads(made.call("graph_continue", {"task": "update()"})[0])
        assert "being built" in result["note"] and made.greps == flow.CAPS["low"][0]
        with pytest.raises(RuntimeError, match="being built"):
            made.call("graph_callers", {"symbol": "update"})

    def test_serve_skips_the_update_while_the_tree_is_at_the_built_head(self, home, monkeypatch):
        data = graph.data_dir("graphify", ROOT)
        data.mkdir(parents=True)
        (data / "graph.json").write_text("{}")
        graph.built_at("graphify", ROOT).write_text("abc")
        _, built, execs = self.serve(monkeypatch, head="abc")
        assert built == [] and len(execs) == 1
        assert self.serve(monkeypatch, head="def")[1] == [ROOT]

    def test_main_rejects_bad_arguments(self, home, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        assert graph.main(["mode", "both"]) == 2
        assert graph.main(["mode", "graphify", "gate"]) == 2
        assert graph.main(["mode", "graperoot"]) == 2
        assert graph.main(["gate", "post"]) == 2
        assert graph.main(["update", "graphify"]) == 2
        assert graph.main(["serve", "all"]) == 2
        assert "usage" in capsys.readouterr().err

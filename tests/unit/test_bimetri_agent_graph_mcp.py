# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 1): local code graph MCP setup on the workers."""

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _agent_graph_config as config  # noqa: E402
import _agent_graph_mcp as graph  # noqa: E402

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

    def test_tool_env_points_each_tool_at_its_data_dir(self, home):
        data = str(graph.data_dir("graphify", ROOT))
        env = graph.tool_env("graphify", ROOT)
        assert env["GRAPHIFY_OUT"] == data
        assert env["GRAPHIFY_QUERY_LOG_DISABLE"] == "1"
        env = graph.tool_env("graperoot", ROOT)
        assert env["DG_DATA_DIR"] == str(graph.data_dir("graperoot", ROOT))
        assert env["DUAL_GRAPH_PROJECT_ROOT"] == str(ROOT)

    def test_commands_use_the_tool_venv(self, home):
        venv = home / ".local/share/bimetri-graph"
        assert graph.update_command("graphify", ROOT) == [
            str(venv / "graphify/bin/graphify"),
            "update",
            str(ROOT),
        ]
        command = graph.update_command("graperoot", ROOT)
        assert command[:3] == [str(venv / "graperoot/bin/python"), "-I", "-c"]
        assert command[-1] == str(ROOT)
        assert graph.server_command("graphify", ROOT)[-1].endswith(
            "workspaces__Org__repo/graph.json"
        )
        assert graph.server_command("graperoot", ROOT)[-2:] == [
            "graperoot.mcp_graph_server",
            "--stdio",
        ]


class TestInstallBundle:
    def test_split_bundle_separates_source_and_locks(self):
        source, locks = graph.split_bundle(
            "print(1)\n### lock: graphify\na==1\n### lock: graperoot\nb==2\nc==3\n"
        )
        assert source == "print(1)\n"
        assert locks == {"graphify": "a==1\n", "graperoot": "b==2\nc==3\n"}

    def test_install_refuses_a_missing_lock(self, home, capsys):
        assert graph.install("print(1)\n### lock: graphify\na==1\n") == 1
        assert "graperoot" in capsys.readouterr().err
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

    def serve(self, monkeypatch, rc, head=None):
        git = SimpleNamespace(returncode=0, stdout=f"{ROOT}\n")
        monkeypatch.setattr(graph.subprocess, "run", lambda *a, **kw: git)
        monkeypatch.setattr(graph, "clean_head", lambda root: head)
        built, execs = [], []
        monkeypatch.setattr(graph, "update", lambda tool, root, out=None: built.append(out) or rc)
        monkeypatch.setattr(graph.os, "execve", lambda *args: execs.append(args))
        return graph.serve("graperoot"), built, execs

    def test_serve_updates_on_stderr_then_execs(self, home, monkeypatch, capsys):
        _, built, execs = self.serve(monkeypatch, 0)
        assert built == [sys.stderr]
        assert execs[0][1] == graph.server_command("graperoot", ROOT)
        assert execs[0][2]["DG_DATA_DIR"] == str(graph.data_dir("graperoot", ROOT))
        assert capsys.readouterr().out == ""  # stdout belongs to MCP

    def test_failed_update_serves_only_an_existing_graph(self, home, monkeypatch):
        assert self.serve(monkeypatch, 1)[0] == 1
        data = graph.data_dir("graperoot", ROOT)
        data.mkdir(parents=True)
        (data / "info_graph.json").write_text("{}")
        assert len(self.serve(monkeypatch, 1)[2]) == 1

    def test_serve_skips_the_update_while_the_tree_is_at_the_built_head(self, home, monkeypatch):
        data = graph.data_dir("graperoot", ROOT)
        data.mkdir(parents=True)
        (data / "info_graph.json").write_text("{}")
        graph.built_at("graperoot", ROOT).write_text("abc")
        _, built, execs = self.serve(monkeypatch, 0, head="abc")
        assert built == [] and len(execs) == 1
        assert self.serve(monkeypatch, 0, head="def")[1] == [sys.stderr]

    def test_main_rejects_bad_arguments(self, home, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        assert graph.main(["mode", "both"]) == 2
        assert graph.main(["mode", "graphify", "open"]) == 2
        assert graph.main(["gate", "post"]) == 2
        assert graph.main(["update", "graphify"]) == 2
        assert graph.main(["serve", "all"]) == 2
        assert "usage" in capsys.readouterr().err

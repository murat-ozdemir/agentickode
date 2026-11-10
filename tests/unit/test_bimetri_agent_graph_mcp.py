# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 1): local code graph MCP setup on the workers."""

import io
import json
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _agent_graph_mcp as graph  # noqa: E402

ROOT = Path("/workspaces/Org/repo")
ENTRY = ["/usr/bin/python3", "/h/.local/share/bimetri-graph/agent_graph.py", "serve", "graperoot"]


@pytest.fixture
def home(tmp_path, monkeypatch):
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


class TestCodexConfig:
    def test_replaces_earlier_entry_and_keeps_the_rest(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            'model = "gpt-5"\n\n[mcp_servers.bimetri-graph]\ncommand = "old"\n\n'
            '[mcp_servers.bimetri-memory]\nurl = "http://m/mcp"\n'
        )
        graph.update_codex(path, ENTRY)
        config = tomllib.loads(path.read_text())
        assert config["model"] == "gpt-5"
        assert config["mcp_servers"]["bimetri-memory"] == {"url": "http://m/mcp"}
        assert config["mcp_servers"]["bimetri-graph"] == {
            "command": ENTRY[0],
            "args": ENTRY[1:],
            "startup_timeout_sec": 120,
        }
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_none_removes_the_entry(self, tmp_path):
        path = tmp_path / "config.toml"
        graph.update_codex(path, ENTRY)
        graph.update_codex(path, None)
        assert path.read_text() == ""


class TestClaudeConfig:
    def test_adds_and_removes_entry_keeping_other_keys(self, tmp_path):
        path = tmp_path / ".claude.json"
        path.write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"type": "http"}}}))
        graph.update_claude(path, ENTRY)
        data = json.loads(path.read_text())
        assert data["theme"] == "dark"
        assert data["mcpServers"]["bimetri-graph"] == {
            "type": "stdio",
            "command": ENTRY[0],
            "args": ENTRY[1:],
            "env": {},
        }
        graph.update_claude(path, None)
        assert json.loads(path.read_text())["mcpServers"] == {"other": {"type": "http"}}
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_settings_raise_the_startup_timeout_and_disable_connectors(self, tmp_path):
        path = tmp_path / ".claude" / "settings.json"
        graph.update_claude_settings(path, "graphify")
        assert json.loads(path.read_text()) == {
            "env": {"MCP_TIMEOUT": "120000"},
            "disableClaudeAiConnectors": True,
        }
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_none_drops_only_the_timeout(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"model": "x", "env": {"A": "1", "MCP_TIMEOUT": "120000"}}))
        graph.update_claude_settings(path, "none")
        assert json.loads(path.read_text()) == {
            "model": "x",
            "env": {"A": "1"},
            "disableClaudeAiConnectors": True,
        }

    def test_set_mode_skips_codex_without_login(self, home, capsys):
        assert graph.set_mode("graphify") == 0
        assert "skipped" in capsys.readouterr().out
        assert not (home / ".codex").exists()
        assert "bimetri-graph" in json.loads((home / ".claude.json").read_text())["mcpServers"]
        assert (home / ".claude" / "settings.json").exists()


class TestUpdateAndServe:
    def test_update_reports_rc_and_time(self, home, monkeypatch, capsys):
        calls = []
        monkeypatch.setattr(
            graph.subprocess,
            "run",
            lambda cmd, **kw: calls.append((cmd, kw)) or SimpleNamespace(returncode=3),
        )
        assert graph.update("graphify", ROOT) == 3
        assert calls[0][1]["cwd"] == ROOT and calls[0][1]["stdout"] == 2
        assert capsys.readouterr().out.startswith("graphify: update rc=3 in ")

    def test_serve_outside_git_fails(self, home, monkeypatch, capsys):
        monkeypatch.setattr(
            graph.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=128, stdout="")
        )
        assert graph.serve("graphify") == 1
        assert "not inside a git clone" in capsys.readouterr().err

    def serve(self, monkeypatch, rc):
        git = SimpleNamespace(returncode=0, stdout=f"{ROOT}\n")
        monkeypatch.setattr(graph.subprocess, "run", lambda *a, **kw: git)
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

    def test_main_rejects_bad_arguments(self, home, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        assert graph.main(["mode", "both"]) == 2
        assert graph.main(["update", "graphify"]) == 2
        assert graph.main(["serve", "all"]) == 2
        assert "usage" in capsys.readouterr().err


class TestShellScript:
    script = _DIR / "agent-graph-mcp.sh"

    def run(self, *args):
        return subprocess.run(["bash", str(self.script), *args], capture_output=True, text=True)

    def test_dry_run_prints_ssh_commands_per_host(self):
        done = self.run("--dry-run", "--repo", "/w/r", "install", "10.0.0.1")
        assert done.returncode == 0
        lines = done.stdout.splitlines()
        assert lines[0] == "== 10.0.0.1"
        assert lines[1].endswith("-c <scripts/bimetri/_agent_graph_mcp.py> install")
        assert lines[2].endswith("<scripts/bimetri/_agent_graph_mcp.py> update all /w/r")
        assert "runuser -u coder" in lines[1]

    def test_mode_lists_the_registered_server(self):
        done = self.run("--dry-run", "mode", "none", "h1", "h2")
        assert done.stdout.count("_agent_graph_mcp.py> mode none") == 2
        # Listed inside the clone: serve only starts where git finds a work tree.
        assert (
            r"-c cd\ /workspaces/Bienport-IoT/platform-backend\ \&\&\ claude\ mcp\ list"
            in done.stdout
        )

    def test_rejects_unknown_mode(self):
        done = self.run("--dry-run", "mode", "both", "h1")
        assert done.returncode == 2 and "usage" in done.stderr

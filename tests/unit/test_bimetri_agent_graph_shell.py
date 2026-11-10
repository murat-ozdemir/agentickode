# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 1-2): agent-graph-mcp.sh, the SSH side of the code graph MCP setup."""

import os
import subprocess
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _agent_graph_mcp as graph  # noqa: E402


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

    def test_direct_runs_as_the_ssh_login_with_one_program(self, tmp_path):
        # A fake ssh records each call; install pipes the program and the locks to it.
        (tmp_path / "ssh").write_text(
            '#!/bin/sh\nn=$(ls "$OUT" | grep -c args)\n'
            'printf "%s\\n" "$@" > "$OUT/$n.args"\ncat > "$OUT/$n.stdin"\n'
        )
        (tmp_path / "ssh").chmod(0o755)
        out = tmp_path / "out"
        out.mkdir()
        env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "OUT": str(out)}
        done = subprocess.run(
            ["bash", str(self.script), "--direct", "install", "agent1-coder"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert done.returncode == 0, done.stderr
        args = (out / "0.args").read_text().splitlines()
        assert args[0] == "agent1-coder" and args[1].startswith("python3 -c ")
        program, locks, files = graph.split_bundle((out / "0.stdin").read_text())
        assert sorted(locks) == ["graphify"] and sorted(files) == ["graph_flow.py"]
        assert "bundle: drop" not in program and "def set_mode" in program
        # The bundled program runs on its own: config first, then the main module.
        ran = subprocess.run([sys.executable, "-I", "-c", program], capture_output=True, text=True)
        assert ran.returncode == 2 and "usage" in ran.stderr
        # So does the flow server, core first; mcp and graphify are imported only in main.
        flow = files["graph_flow.py"]
        assert "from _graph_flow import" not in flow and "def continue_flow" in flow
        compile(flow, "graph_flow.py", "exec")
        ran = subprocess.run(
            [sys.executable, "-I", "-c", flow.replace('if __name__ == "__main__":', "if 0:")],
            capture_output=True,
            text=True,
        )
        assert ran.returncode == 0, ran.stderr

    def test_rejects_unknown_mode_and_the_old_options(self):
        for args in (("mode", "both"), ("mode", "graperoot"), ("--gate", "mode", "graphify")):
            done = self.run("--dry-run", *args, "h1")
            assert done.returncode == 2, args

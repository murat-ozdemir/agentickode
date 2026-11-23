# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 10): Codex's managed whole-read hook file."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _codex_read_hook as hook  # noqa: E402

OTHER = {"matcher": "^Bash$", "hooks": [{"type": "command", "command": "/opt/audit.sh"}]}


@pytest.fixture
def path(tmp_path):
    return tmp_path / "etc" / "codex" / "hooks.json"


@pytest.fixture
def version(monkeypatch):
    found = {"out": "codex-cli 0.130.0\n"}

    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, found["out"], "")

    monkeypatch.setattr(hook.subprocess, "run", run)
    monkeypatch.setattr(hook, "has_gate_read", lambda user: True)
    return found


class TestHooksFile:
    def test_on_writes_the_bash_hook_readable_by_every_worker(self, path):
        hook.update_hooks(path, on=True)
        data = json.loads(path.read_text())
        assert data == {"hooks": {"PreToolUse": [hook.HOOK]}}
        assert hook.MARK in hook.COMMAND and "gate read" in hook.COMMAND
        assert path.stat().st_mode & 0o777 == 0o644

    def test_keeps_other_hooks_and_is_written_once(self, path):
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"hooks": {"PreToolUse": [OTHER], "Stop": [OTHER]}}))
        hook.update_hooks(path, on=True)
        hook.update_hooks(path, on=True)
        assert json.loads(path.read_text())["hooks"]["PreToolUse"] == [OTHER, hook.HOOK]
        hook.update_hooks(path, on=False)
        assert json.loads(path.read_text()) == {"hooks": {"PreToolUse": [OTHER], "Stop": [OTHER]}}

    def test_off_on_a_worker_without_the_file_writes_nothing(self, path):
        hook.update_hooks(path, on=False)
        assert not path.exists()

    def test_hook_command_skips_a_worker_without_the_program(self, tmp_path):
        done = subprocess.run(
            ["/bin/sh", "-c", hook.COMMAND], env={"HOME": str(tmp_path)}, input="{}", text=True
        )
        assert done.returncode == 0

    @pytest.mark.parametrize(
        ("err", "code", "blocked"),
        [
            ("usage: install | update TOOL|all ROOT | gate pre|mark", 2, False),  # run 294
            ("Traceback (most recent call last): ...", 1, False),
            ("", 0, False),
            ("Read src/Big.java with graph_read.", 2, True),
        ],
    )
    def test_hook_command_blocks_only_on_the_gates_refusal(self, tmp_path, err, code, blocked):
        program = tmp_path / hook.PROGRAM
        program.parent.mkdir(parents=True)
        program.write_text(f"import sys\nsys.stderr.write({err!r})\nsys.exit({code})\n")
        done = subprocess.run(
            ["/bin/sh", "-c", hook.COMMAND],
            env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
            input="{}",
            text=True,
            capture_output=True,
        )
        assert done.returncode == (2 if blocked else 0)
        assert (bool(err) and err in done.stderr) == blocked


class TestMain:
    def test_graphify_prints_the_codex_version(self, path, version, capsys):
        assert hook.main(["graphify", "coder"], path) == 0
        assert capsys.readouterr().out == f"codex hook: on ({path}), codex 0.130.0\n"

    def test_warns_when_codex_is_older_than_hooks(self, path, version, capsys):
        version["out"] = "codex-cli 0.120.3\n"
        assert hook.main(["graphify", "coder"], path) == 0
        assert "WARNING: hooks need codex 0.124.0 or later" in capsys.readouterr().out

    def test_warns_when_the_program_has_no_gate_read(self, path, version, monkeypatch, capsys):
        monkeypatch.setattr(hook, "has_gate_read", lambda user: False)
        assert hook.main(["graphify", "coder"], path) == 0
        assert "has no `gate read`" in capsys.readouterr().out

    def test_has_gate_read_reads_the_workers_program(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hook.os.path, "expanduser", lambda p: str(tmp_path))
        assert not hook.has_gate_read("coder")
        (tmp_path / hook.PROGRAM).parent.mkdir(parents=True)
        (tmp_path / hook.PROGRAM).write_text('args in (["pre"], ["mark"])')
        assert not hook.has_gate_read("coder")
        (tmp_path / hook.PROGRAM).write_text('args in (["pre"], ["mark"], ["read"])')
        assert hook.has_gate_read("coder")

    def test_none_drops_the_hook(self, path, version, capsys):
        hook.main(["graphify", "coder"], path)
        assert hook.main(["none", "coder"], path) == 0
        assert "PreToolUse" not in path.read_text()
        assert capsys.readouterr().out.endswith(f"codex hook: off ({path})\n")

    def test_rejects_other_modes(self, path, capsys):
        assert hook.main(["both", "coder"], path) == 2
        assert not path.exists()

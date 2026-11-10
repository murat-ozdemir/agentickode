# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 1): agent CLI settings for the code graph MCP on the workers."""

# ruff: noqa: RUF001 - Turkish text; dotless i is a letter there

import json
import stat
import sys
import tomllib
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _agent_graph_config as config  # noqa: E402

ENTRY = ["/usr/bin/python3", "/h/.local/share/bimetri-graph/agent_graph.py", "serve", "graperoot"]
CLAUDE_ENV = {"MCP_TIMEOUT": "120000", "MCP_CONNECT_TIMEOUT_MS": "15000"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "home", lambda: tmp_path)
    return tmp_path


class TestCodexConfig:
    def test_replaces_earlier_entry_and_keeps_the_rest(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            'model = "gpt-5"\n\n[mcp_servers.bimetri-graph]\ncommand = "old"\n\n'
            '[mcp_servers.bimetri-memory]\nurl = "http://m/mcp"\n'
        )
        config.update_codex(path, ENTRY)
        data = tomllib.loads(path.read_text())
        assert data["model"] == "gpt-5"
        assert data["mcp_servers"]["bimetri-memory"] == {"url": "http://m/mcp"}
        assert data["mcp_servers"]["bimetri-graph"] == {
            "command": ENTRY[0],
            "args": ENTRY[1:],
            "startup_timeout_sec": 120,
        }
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_none_removes_the_entry(self, tmp_path):
        path = tmp_path / "config.toml"
        config.update_codex(path, ENTRY)
        config.update_codex(path, None)
        assert path.read_text() == ""


class TestClaudeConfig:
    def test_adds_and_removes_entry_keeping_other_keys(self, tmp_path):
        path = tmp_path / ".claude.json"
        path.write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"type": "http"}}}))
        config.update_claude(path, ENTRY)
        data = json.loads(path.read_text())
        assert data["theme"] == "dark"
        # alwaysLoad: tools in the first turn's tool list, not behind tool search.
        assert data["mcpServers"]["bimetri-graph"] == {
            "type": "stdio",
            "command": ENTRY[0],
            "args": ENTRY[1:],
            "env": {},
            "alwaysLoad": True,
        }
        config.update_claude(path, None)
        assert json.loads(path.read_text())["mcpServers"] == {"other": {"type": "http"}}
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_settings_raise_the_startup_waits_and_disable_connectors(self, tmp_path):
        path = tmp_path / ".claude" / "settings.json"
        config.update_claude_settings(path, "graphify")
        assert json.loads(path.read_text()) == {
            "env": CLAUDE_ENV,
            "disableClaudeAiConnectors": True,
        }
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_none_drops_only_the_waits(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"model": "x", "env": {"A": "1", **CLAUDE_ENV}}))
        config.update_claude_settings(path, "none")
        assert json.loads(path.read_text()) == {
            "model": "x",
            "env": {"A": "1"},
            "disableClaudeAiConnectors": True,
        }


class TestHint:
    def test_appends_the_hint_after_existing_text(self, tmp_path):
        path = tmp_path / "CLAUDE.md"
        path.write_text("# Kendi notlarım\n")
        config.update_hint(path, True)
        text = path.read_text()
        assert text.startswith("# Kendi notlarım\n\n" + config.HINT_START + "\n")
        assert config.HINT in text and text.endswith(config.HINT_END + "\n")

    def test_is_idempotent(self, tmp_path):
        path = tmp_path / "CLAUDE.md"
        config.update_hint(path, True)
        once = path.read_text()
        config.update_hint(path, True)
        assert path.read_text() == once and once.count(config.HINT_START) == 1

    def test_off_removes_only_the_hint(self, tmp_path):
        path = tmp_path / "AGENTS.md"
        path.write_text("önce\n")
        config.update_hint(path, True)
        path.write_text(path.read_text() + "\nsonra\n")
        config.update_hint(path, False)
        assert path.read_text() == "önce\n\nsonra\n"

    def test_off_creates_no_file(self, tmp_path):
        config.update_hint(tmp_path / "x" / "CLAUDE.md", False)
        assert not (tmp_path / "x").exists()


class TestSetMode:
    def test_skips_codex_without_login(self, home, capsys):
        assert config.set_mode("graphify") == 0
        assert "skipped" in capsys.readouterr().out
        assert not (home / ".codex").exists()
        assert "bimetri-graph" in json.loads((home / ".claude.json").read_text())["mcpServers"]
        assert (home / ".claude" / "settings.json").exists()
        assert config.HINT in (home / ".claude" / "CLAUDE.md").read_text()

    def test_none_takes_the_hint_back_for_both_clis(self, home):
        (home / ".codex").mkdir()
        config.set_mode("graperoot")
        assert config.HINT in (home / ".codex" / "AGENTS.md").read_text()
        config.set_mode("none")
        assert (home / ".codex" / "AGENTS.md").read_text() == ""
        assert (home / ".claude" / "CLAUDE.md").read_text() == ""

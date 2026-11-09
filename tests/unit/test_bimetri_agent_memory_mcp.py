# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (yama 75): agent CLI config for the memory MCP."""

import json
import stat
import sys
import tomllib
from pathlib import Path

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _agent_memory_mcp as setup  # noqa: E402

URL = "http://192.168.20.50:8892/mcp"


class TestCodexConfig:
    def test_replaces_earlier_entry_and_keeps_the_rest(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            'model = "gpt-5"\n\n[mcp_servers.bimetri-memory]\nurl = "http://old/mcp"\n\n'
            '[mcp_servers.bimetri-memory.tools.x]\nenabled = false\n\n[projects."/w"]\ntrust_level = "trusted"\n'
        )
        setup.update_codex(path, URL, "tok")
        config = tomllib.loads(path.read_text())
        assert config["model"] == "gpt-5"
        assert config["projects"]["/w"] == {"trust_level": "trusted"}
        assert config["mcp_servers"] == {
            "bimetri-memory": {"url": URL, "http_headers": {"Authorization": "Bearer tok"}}
        }
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_creates_missing_file(self, tmp_path):
        path = tmp_path / "config.toml"
        setup.update_codex(path, URL, "tok")
        assert path.read_text().startswith("[mcp_servers.bimetri-memory]\n")


class TestClaudeConfig:
    def test_adds_user_scope_server_and_keeps_other_keys(self, tmp_path):
        path = tmp_path / ".claude.json"
        path.write_text(json.dumps({"oauthAccount": {"x": 1}, "mcpServers": {"other": {}}}))
        setup.update_claude(path, URL, "tok")
        data = json.loads(path.read_text())
        assert data["oauthAccount"] == {"x": 1}
        assert data["mcpServers"]["other"] == {}
        assert data["mcpServers"]["bimetri-memory"] == {
            "type": "http",
            "url": URL,
            "headers": {"Authorization": "Bearer tok"},
        }
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


class TestMain:
    def test_writes_both_without_printing_the_token(self, tmp_path, monkeypatch, capsys):
        (tmp_path / ".codex").mkdir()
        monkeypatch.setattr(setup.pwd, "getpwuid", lambda _: type("P", (), {"pw_dir": tmp_path}))
        monkeypatch.setattr(sys, "argv", ["x", URL])
        monkeypatch.setattr(sys, "stdin", type("S", (), {"readline": lambda self: "secret\n"})())
        assert setup.main() == 0
        assert "secret" not in capsys.readouterr().out
        assert "Bearer secret" in (tmp_path / ".codex" / "config.toml").read_text()
        assert "Bearer secret" in (tmp_path / ".claude.json").read_text()

    def test_refuses_empty_token(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["x", URL])
        monkeypatch.setattr(sys, "stdin", type("S", (), {"readline": lambda self: "\n"})())
        assert setup.main() == 1

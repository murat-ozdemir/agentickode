"""bimetri patch (yama 75): register the memory-mcp server in the agent CLIs' user config.

Runs on a worker as the worker user (agent-memory-mcp.sh sends it over SSH):
    python3 _agent_memory_mcp.py <url>      # bearer token on the first stdin line
Writes ~/.codex/config.toml ([mcp_servers.bimetri-memory]) and ~/.claude.json (mcpServers,
user scope), replacing an earlier entry. Both files end up 0600; the token is never printed.
Python 3.8+, standard library only.
"""

import json
import os
import pwd
import re
import sys
from pathlib import Path

NAME = "bimetri-memory"
_CODEX_TABLE = re.compile(r"^\[mcp_servers\.(?:\"bimetri-memory\"|bimetri-memory)[.\]]")


def _write_private(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(str(tmp), 0o600)
    os.replace(str(tmp), str(path))


def update_codex(path: Path, url: str, token: str) -> None:
    kept, skipping = [], False
    for line in path.read_text().splitlines() if path.exists() else []:
        if line.startswith("["):
            skipping = bool(_CODEX_TABLE.match(line))
        if not skipping:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    block = [
        f"[mcp_servers.{NAME}]",
        f"url = {json.dumps(url)}",
        f"http_headers = {{ Authorization = {json.dumps('Bearer ' + token)} }}",
    ]
    _write_private(path, "\n".join(kept + ([""] if kept else []) + block) + "\n")


def update_claude(path: Path, url: str, token: str) -> None:
    data = json.loads(path.read_text()) if path.exists() else {}
    data.setdefault("mcpServers", {})[NAME] = {
        "type": "http",
        "url": url,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    _write_private(path, json.dumps(data, indent=2) + "\n")


def main() -> int:
    url = sys.argv[1]
    token = sys.stdin.readline().strip()
    if not token:
        print("ERROR: no token on stdin")
        return 1
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    codex_dir = home / ".codex"
    if codex_dir.is_dir():
        update_codex(codex_dir / "config.toml", url, token)
        print("codex:  written")
    else:
        print("codex:  skipped (~/.codex missing, log in first)")
    update_claude(home / ".claude.json", url, token)
    print("claude: written")
    return 0


if __name__ == "__main__":
    sys.exit(main())

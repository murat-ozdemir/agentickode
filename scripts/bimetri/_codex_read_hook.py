"""bimetri patch (loop efficiency item 10): Codex's whole-read hook in /etc/codex/hooks.json.

agent-graph-mcp.sh runs this as root on the worker (`python3 -c <this file> MODE USER`) beside
`mode`. Hooks in the system hooks file are managed: Codex runs them without a /hooks review.
The hook calls the worker's agent_graph.py `gate read` (_agent_graph_gate.py): reading a large
source file whole in the shell (cat, sed -n 1,400p, ...) is denied once per file with a pointer
to graph_read. Mode none drops this hook and keeps any other. Hooks are stable from Codex CLI
0.124.0; an older codex is reported, not updated. Stdlib only.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOOKS = Path("/etc/codex/hooks.json")
MIN_VERSION = (0, 124, 0)
MARK = "bimetri-graph/agent_graph.py"  # in COMMAND; tells our hook from others
# Codex runs the hook as the worker, in its shell: $HOME is the worker's. No program, no hook.
COMMAND = (
    'f="$HOME/.local/share/bimetri-graph/agent_graph.py"; [ -f "$f" ] || exit 0; '
    'exec python3 "$f" gate read'
)
HOOK = {"matcher": "^Bash$", "hooks": [{"type": "command", "command": COMMAND, "timeout": 5}]}


def _ours(group: dict) -> bool:
    return any(MARK in str(h.get("command", "")) for h in group.get("hooks", []))


def update_hooks(path: Path, on: bool) -> None:
    data = json.loads(path.read_text()) if path.exists() else {}
    hooks = data.get("hooks", {})
    pre = [g for g in hooks.get("PreToolUse", []) if not _ours(g)] + ([HOOK] if on else [])
    hooks = {**hooks, "PreToolUse": pre}
    data["hooks"] = {event: groups for event, groups in hooks.items() if groups}
    if not data["hooks"]:
        data.pop("hooks")
    if not data and not path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(tmp, 0o644)  # every worker user's codex reads it
    os.replace(tmp, path)


def codex_version(user: str) -> "tuple | None":
    done = subprocess.run(
        ["runuser", "-l", user, "-c", "codex --version"], capture_output=True, text=True
    )
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", done.stdout)
    return tuple(int(n) for n in found.groups()) if found else None


def main(argv: list, path: Path = HOOKS) -> int:
    if len(argv) != 2 or argv[0] not in ("graphify", "none"):
        print("usage: graphify|none WORKER_USER", file=sys.stderr)
        return 2
    on = argv[0] == "graphify"
    update_hooks(path, on)
    if not on:
        print(f"codex hook: off ({path})")
        return 0
    version = codex_version(argv[1])
    shown = ".".join(map(str, version)) if version else "not found"
    print(f"codex hook: on ({path}), codex {shown}")
    if version and version < MIN_VERSION:
        need = ".".join(map(str, MIN_VERSION))
        print(f"WARNING: hooks need codex {need} or later; update codex for {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

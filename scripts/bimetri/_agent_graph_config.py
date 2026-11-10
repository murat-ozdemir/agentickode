"""bimetri patch (D2 phase 1): agent CLI settings for the code graph MCP on a worker (`mode`).

agent-graph-mcp.sh ships this file and _agent_graph_mcp.py as one program, this one first.
Writes, as the worker user:
    ~/.claude.json            bimetri-graph stdio server, tools loaded up front (alwaysLoad)
    ~/.claude/settings.json   startup waits, claude.ai connectors off
    ~/.codex/config.toml      bimetri-graph server with its startup timeout
    ~/.claude/CLAUDE.md, ~/.codex/AGENTS.md   a marked hint telling the agent to use the graph
With gate, ~/.claude/settings.json also gets hooks that deny Claude every other tool until it has
called a graph tool in that session (`gate pre|mark`, below), for a measured run.
Mode none removes all of it except the connector switch. Stdlib only.
"""

# ruff: noqa: RUF001 - the agent hint is Turkish; dotless i is a letter there

import json
import os
import pwd
import re
import shlex
import sys
from pathlib import Path

NAME = "bimetri-graph"
TOOLS = ("graphify", "graperoot")
# serve updates the graph before it answers: 51.7 s on platform-backend after a 3-file checkout.
STARTUP_TIMEOUT_SEC = 120
CLAUDE_ENV = {
    "MCP_TIMEOUT": str(STARTUP_TIMEOUT_SEC * 1000),  # one server's connect attempt; default 30 s
    # How long startup waits for alwaysLoad servers before it builds the tool list; default 5 s.
    "MCP_CONNECT_TIMEOUT_MS": "15000",
}
HINT_START, HINT_END = f"<!-- {NAME}: start -->", f"<!-- {NAME}: end -->"
HINT = (
    f"Bu makinede `{NAME}` MCP sunucusu deponun kod grafiğini sunar. Bir sembolü kimin "
    "çağırdığını, nerede kullanıldığını ya da bir değişikliğin neyi etkileyeceğini bulmak için "
    "grep'ten önce bu sunucunun araçlarını kullan. Grafiğin sonucunu, değiştireceğin dosyayı "
    "okuyarak doğrula."
)
GATE_DENY = (
    "Bu ölçümde önce `{name}` araçlarıyla değişikliğin etkisini bul (çağıranlar, kullanımlar). "
    "Bir `{name}` aracını çağırana kadar {tool} ve öteki araçlar kapalı."
)
GRAPH_TOOLS = f"mcp__{NAME}__"
# Claude's own tool search stays open: with alwaysLoad it is not needed, but it is no workaround.
GATE_OPEN = ("ToolSearch",)
_CODEX_TABLE = re.compile(r"^\[mcp_servers\.(?:\"bimetri-graph\"|bimetri-graph)[.\]]")


def home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def base_dir() -> Path:
    return home() / ".local" / "share" / NAME


def _write_private(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(str(tmp), 0o600)
    os.replace(str(tmp), str(path))


def update_codex(path: Path, entry: "list | None") -> None:
    kept, skipping = [], False
    for line in path.read_text().splitlines() if path.exists() else []:
        if line.startswith("["):
            skipping = bool(_CODEX_TABLE.match(line))
        if not skipping:
            kept.append(line)
    if entry:
        kept += ["", f"[mcp_servers.{NAME}]", f"command = {json.dumps(entry[0])}"]
        kept += [f"args = {json.dumps(entry[1:])}", f"startup_timeout_sec = {STARTUP_TIMEOUT_SEC}"]
    text = "\n".join(kept).strip()
    _write_private(path, text + "\n" if text else "")


def update_claude(path: Path, entry: "list | None") -> None:
    data = json.loads(path.read_text()) if path.exists() else {}
    servers = data.setdefault("mcpServers", {})
    servers.pop(NAME, None)
    if entry:
        # MCP tools are deferred behind tool search by default, and claude -p does not wait for
        # them: in measurement B the agent never saw the graph. alwaysLoad fixes both.
        servers[NAME] = {"type": "stdio", "command": entry[0], "args": entry[1:], "env": {}}
        servers[NAME]["alwaysLoad"] = True
    _write_private(path, json.dumps(data, indent=2) + "\n")


def gate_hooks(command: list) -> dict:
    def hook(step: str) -> list:
        return [{"type": "command", "command": shlex.join([*command, step]), "timeout": 5}]

    # PostToolUseFailure too: a graph call that errors still counts as using the graph, and the
    # agent must not be locked out by it.
    mark = [{"matcher": f"{GRAPH_TOOLS}.*", "hooks": hook("mark")}]
    return {
        "PreToolUse": [{"matcher": "*", "hooks": hook("pre")}],
        "PostToolUse": mark,
        "PostToolUseFailure": mark,
    }


def _is_gate(group: dict) -> bool:
    return any("agent_graph.py gate " in h.get("command", "") for h in group.get("hooks", []))


def update_claude_settings(path: Path, mode: str, gate: "list | None" = None) -> None:
    """gate: the hook command without its step; None removes the gate hooks."""
    data = json.loads(path.read_text()) if path.exists() else {}
    env = data["env"] = {k: v for k, v in data.get("env", {}).items() if k not in CLAUDE_ENV}
    if mode in TOOLS:
        env.update(CLAUDE_ENV)
    hooks = {
        event: kept
        for event, groups in data.get("hooks", {}).items()
        if (kept := [g for g in groups if not _is_gate(g)])
    }
    if gate and mode in TOOLS:
        for event, groups in gate_hooks(gate).items():
            hooks.setdefault(event, []).extend(groups)
    data.pop("hooks", None)
    if hooks:
        data["hooks"] = hooks
    # Workers log in with the operator's claude.ai subscription; keep its connectors (mail, drive,
    # calendar) away from the agents. Applies to this machine only.
    data["disableClaudeAiConnectors"] = True
    path.parent.mkdir(exist_ok=True)
    _write_private(path, json.dumps(data, indent=2) + "\n")


def update_hint(path: Path, on: bool) -> None:
    """Add or drop the marked hint block of a CLI's user-level instructions file."""
    kept, skipping = [], False
    for line in path.read_text().splitlines() if path.exists() else []:
        if line == HINT_START and kept and not kept[-1]:
            kept.pop()  # the blank line set before the block
        skipping = skipping or line == HINT_START
        if not skipping:
            kept.append(line)
        skipping = skipping and line != HINT_END
    text = "\n".join(kept).strip()
    if on:
        text = (text + "\n\n" if text else "") + "\n".join((HINT_START, HINT, HINT_END))
    if text or path.exists():
        path.parent.mkdir(exist_ok=True)
        _write_private(path, text + "\n" if text else "")


def gate(step: str, payload: str) -> int:
    """Claude hook: pre denies (exit 2, reason on stderr) until mark has run in that session."""
    event = json.loads(payload or "{}")
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(event.get("session_id", "")))
    marker = base_dir() / "gate" / f"{session or 'unknown'}.ok"
    if step == "mark":
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        return 0
    tool = str(event.get("tool_name", ""))
    if tool.startswith(GRAPH_TOOLS) or tool in GATE_OPEN or marker.exists():
        return 0
    print(GATE_DENY.format(name=NAME, tool=tool), file=sys.stderr)
    return 2


def set_mode(mode: str, with_gate: bool = False) -> int:
    program = [sys.executable, str(base_dir() / "agent_graph.py")]
    entry = [*program, "serve", mode] if mode in TOOLS else None
    if (home() / ".codex").is_dir():
        update_codex(home() / ".codex" / "config.toml", entry)
        update_hint(home() / ".codex" / "AGENTS.md", bool(entry))
        print(f"codex:  {mode}")
    else:
        print("codex:  skipped (~/.codex missing, log in first)")
    update_claude(home() / ".claude.json", entry)
    gate_command = [*program, "gate"] if with_gate and entry else None
    update_claude_settings(home() / ".claude" / "settings.json", mode, gate_command)
    update_hint(home() / ".claude" / "CLAUDE.md", bool(entry))
    print(f"claude: {mode}{', gate on' if gate_command else ''}, claude.ai connectors off")
    return 0

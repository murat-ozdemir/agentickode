"""bimetri patch (D2 phase 1-2): agent CLI settings for the code graph MCP on a worker (`mode`).

agent-graph-mcp.sh ships this file, _agent_graph_gate.py and _agent_graph_mcp.py as one program.
Writes, as the worker user:
    ~/.claude.json            bimetri-graph stdio server, tools loaded up front (alwaysLoad)
    ~/.claude/settings.json   startup waits, claude.ai connectors off
    ~/.codex/config.toml      bimetri-graph server with its startup timeout
    ~/.claude/CLAUDE.md, ~/.codex/AGENTS.md   the marked graph policy (graph_continue first, caps)
~/.claude/settings.json also gets the gate hooks (_agent_graph_gate.py): no other tool before
graph_continue, searches within its grep budget. Codex has no hooks, only the policy.
Mode none removes all of it except the connector switch. Stdlib only.
"""

# ruff: noqa: RUF001 - the agent policy is Turkish; dotless i is a letter there

import json
import os
import pwd
import re
import shlex
import sys
from pathlib import Path

from _agent_graph_gate import GATE_FIRST  # bundle: drop

NAME = "bimetri-graph"
TOOLS = ("graphify",)
# serve answers in ~2 s (loading a 42 MB graph) and updates in the background; the margin is for
# a busy worker.
STARTUP_TIMEOUT_SEC = 120
CLAUDE_ENV = {
    "MCP_TIMEOUT": str(STARTUP_TIMEOUT_SEC * 1000),  # one server's connect attempt; default 30 s
    # How long startup waits for alwaysLoad servers before it builds the tool list; default 5 s.
    "MCP_CONNECT_TIMEOUT_MS": "15000",
}
POLICY_START, POLICY_END = f"<!-- {NAME}: start -->", f"<!-- {NAME}: end -->"
# Modelled on the Dual-Graph context policy (graph_continue first, then capped fallbacks).
POLICY = f"""## Kod grafiği akışı (`{NAME}`)

Bu makinede `{NAME}` MCP sunucusu deponun kod grafiğini sunar. Kodu keşfederken bu sırayı izle:

1. Her görevin ya da yeni bir alt görevin başında önce `graph_continue` çağır; görevi kendi
   sözlerinle, ilgili sınıf ve metot adlarıyla yaz. Ondan önce başka araç kullanma.
2. `recommended_files` içindeki girdileri `graph_read` ile oku, her dosya için ayrı çağrı.
   `yol::Sembol` yalnızca o sembolün satırlarını getirir. `yol:SATIR` bir kullanım yeridir: `why`
   o satırın kodunu zaten gösterir; yetmezse `graph_read yol:SATIR` çevresindeki satırları verir.
   Çağıran metodun tamamını okuma.
3. Bir sembolü kimin çağırdığını, nerede kullanıldığını `graph_callers` ile bul, grep ile değil:
   her kullanımı dosya, satır ve o satırdaki kodla verir.
4. `confidence` ne olursa olsun önerilenler yetmezse en çok `max_supplementary_greps` kez
   `fallback_rg` çağır ve en çok `max_supplementary_files` ek dosya oku; sonra dur, yazmaya geç.
   `high` ise önerilen dosyalarla yetinmeye çalış. Arama sınırı Grep, Glob ve kabukta
   `rg`/`grep`/`find` ile yapılan aramaları da kapsar: hak bitince ilk arama reddedilir;
   gerçekten gerekiyorsa (ör. listenin tam olduğunu doğrulamak) tekrarla, geçer.
5. Sınırlar yalnızca keşif içindir: değiştireceğin dosyayı okumak, düzenleme, derleme, test ve
   git komutları serbest.

Grafik son temiz commit'e göredir; senin yaptığın değişiklikler grafikte yoktur."""
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

    # PostToolUseFailure too: a graph_continue that errors must not lock the agent out.
    mark = [{"matcher": GATE_FIRST, "hooks": hook("mark")}]
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


def update_policy(path: Path, on: bool) -> None:
    """Add or drop the marked policy block of a CLI's user-level instructions file."""
    kept, skipping = [], False
    for line in path.read_text().splitlines() if path.exists() else []:
        if line == POLICY_START and kept and not kept[-1]:
            kept.pop()  # the blank line set before the block
        skipping = skipping or line == POLICY_START
        if not skipping:
            kept.append(line)
        skipping = skipping and line != POLICY_END
    text = "\n".join(kept).strip()
    if on:
        text = (text + "\n\n" if text else "") + "\n".join((POLICY_START, POLICY, POLICY_END))
    if text or path.exists():
        path.parent.mkdir(exist_ok=True)
        _write_private(path, text + "\n" if text else "")


def set_mode(mode: str) -> int:
    program = [sys.executable, str(base_dir() / "agent_graph.py")]
    entry = [*program, "serve", mode] if mode in TOOLS else None
    if (home() / ".codex").is_dir():
        update_codex(home() / ".codex" / "config.toml", entry)
        update_policy(home() / ".codex" / "AGENTS.md", bool(entry))
        print(f"codex:  {mode}")
    else:
        print("codex:  skipped (~/.codex missing, log in first)")
    update_claude(home() / ".claude.json", entry)
    gate_command = [*program, "gate"] if entry else None
    update_claude_settings(home() / ".claude" / "settings.json", mode, gate_command)
    update_policy(home() / ".claude" / "CLAUDE.md", bool(entry))
    print(f"claude: {mode}{', gate on' if gate_command else ''}, claude.ai connectors off")
    return 0

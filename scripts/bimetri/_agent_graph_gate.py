"""bimetri patch (D2 phase 2): Claude hook that keeps an agent on the graph flow (`gate pre|mark`).

agent-graph-mcp.sh ships this file first in the worker program; `mode graphify` writes the hooks.
    pre    deny every tool until graph_continue ran in the session. After that, each search
           (Grep, Glob, fallback_rg, or a shell command that starts with rg/grep/find...) draws
           on the grep budget graph_continue returned; at zero, searches are denied.
    mark   after graph_continue: write its max_supplementary_greps to the session's marker.
Stdlib only.
"""

# ruff: noqa: RUF001 - the deny texts are Turkish; dotless i is a letter there

import fcntl
import json
import re
import sys
from pathlib import Path

GATE_FIRST = "mcp__bimetri-graph__graph_continue"
# Claude's own tool search stays open: with alwaysLoad it is not needed, but it is no workaround.
GATE_OPEN = ("ToolSearch",)
SEARCH_TOOLS = ("Grep", "Glob", "mcp__bimetri-graph__fallback_rg")
SEARCH_COMMANDS = ("rg", "grep", "egrep", "fgrep", "ag", "ack", "find", "fd", "locate")
DEFAULT_GREPS = 4  # graph_continue's reply unreadable (it failed): the low-confidence cap
# Command positions in a shell line; a single `|` is not one (`mvn test | grep FAIL` filters).
_COMMANDS = re.compile(r"&&|\|\||[;\n&(`]|\$\(")
GATE_DENY = (
    "Önce `graph_continue` ile görevin dosyalarını al (bkz. CLAUDE.md, kod grafiği akışı). "
    "O çağrıya kadar {tool} ve öteki araçlar kapalı."
)
GATE_SPENT = (
    "Arama sınırı doldu: `graph_continue`'nun verdiği arama hakkı (Grep, Glob, fallback_rg, "
    "kabukta rg/grep/find) bitti. `graph_callers` ve `graph_read` ile devam et, düzenlemeye geç "
    "ya da yeni bir alt görev için yeniden `graph_continue` çağır."
)


def searches(command: str) -> bool:
    """Whether a shell line searches the tree: a search command at a command position, or
    behind xargs. Filtering another command's output through a pipe does not count."""
    for part in _COMMANDS.split(command):
        for i, stage in enumerate(part.split("|")):
            words = [w for w in stage.split() if not re.match(r"\w+=", w)]  # drop VAR=value
            if words[:1] == ["xargs"]:
                words = [w for w in words[1:] if not w.startswith("-")]
            elif i:
                continue
            name = words[0].rsplit("/", 1)[-1] if words else ""
            if name in SEARCH_COMMANDS or words[:2] == ["git", "grep"]:
                return True
    return False


def _spend(marker: Path) -> bool:
    """Take one search from the session's budget; False when none is left."""
    with open(marker, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # parallel tool calls run their hooks at once
        text = f.read().strip()
        left = int(text) if text.isdigit() else DEFAULT_GREPS
        if left <= 0:
            return False
        f.seek(0)
        f.truncate()
        f.write(str(left - 1))
    return True


def gate(step: str, payload: str, marker_dir: Path) -> int:
    """Claude hook: exit 2 (reason on stderr) denies the tool call."""
    event = json.loads(payload or "{}")
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(event.get("session_id", "")))
    marker = marker_dir / f"{session or 'unknown'}.ok"
    if step == "mark":
        reply = json.dumps(event.get("tool_response"))
        found = re.search(r"max_supplementary_greps\W+(\d+)", reply)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(found.group(1) if found else str(DEFAULT_GREPS))
        return 0
    tool = str(event.get("tool_name", ""))
    if tool in (GATE_FIRST, *GATE_OPEN):
        return 0
    if not marker.exists():
        print(GATE_DENY.format(tool=tool), file=sys.stderr)
        return 2
    command = (event.get("tool_input") or {}).get("command", "") if tool == "Bash" else ""
    if (tool in SEARCH_TOOLS or searches(str(command))) and not _spend(marker):
        print(GATE_SPENT, file=sys.stderr)
        return 2
    return 0

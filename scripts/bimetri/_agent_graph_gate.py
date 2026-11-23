"""bimetri patch (D2 phase 2): hooks that keep an agent on the graph flow (`gate pre|mark|read`).

agent-graph-mcp.sh ships this file first in the worker program; `mode graphify` writes the hooks.
    pre    deny every tool until graph_continue ran in the session. After that, each search
           (Grep, Glob, fallback_rg, or a shell command that starts with rg/grep/find...) draws
           on the grep budget graph_continue returned. The first search past it is denied with a
           pointer to graph_callers; after that searches go through (run #95: a hard stop made
           the agent give up on listing every caller).
           Reading a whole large source file (Read without a short limit, or cat/sed/head in the
           shell) is denied once per file with a pointer to graph_read's outline; the same read
           again goes through (graf tasarruf planı Faz 1).
    mark   after graph_continue: write its max_supplementary_greps to the session's marker.
    read   Codex's shell hook (/etc/codex/hooks.json, _codex_read_hook.py): only the whole-read
           rule of pre, once per file; Codex gets no graph_continue gate and no grep budget.
A context pack in the prompt (_graph_pack.py, gate/run-<BIMETRI_RUN_ID>) counts as graph_continue:
the session's marker starts from the pack's grep budget (graf tasarruf planı Faz 2).
Stdlib only.
"""

# ruff: noqa: RUF001 - the deny texts are Turkish; dotless i is a letter there

import fcntl
import json
import os
import re
import shlex
import sys
from pathlib import Path

GATE_FIRST = "mcp__bimetri-graph__graph_continue"
# Claude's own tool search stays open: with alwaysLoad it is not needed, but it is no workaround.
GATE_OPEN = ("ToolSearch",)
SEARCH_TOOLS = ("Grep", "Glob", "mcp__bimetri-graph__fallback_rg")
SEARCH_COMMANDS = ("rg", "grep", "egrep", "fgrep", "ag", "ack", "find", "fd", "locate")
DEFAULT_GREPS = 4  # graph_continue's reply unreadable (it failed): the low-confidence cap
OPEN = "open"  # marker text once the budget was spent and the agent was told
# Command positions in a shell line; a single `|` is not one (`mvn test | grep FAIL` filters).
_COMMANDS = re.compile(r"&&|\|\||[;\n&(`]|\$\(")
GATE_DENY = (
    "Önce `graph_continue` ile görevin dosyalarını al (bkz. CLAUDE.md, kod grafiği akışı). "
    "O çağrıya kadar {tool} ve öteki araçlar kapalı."
)
GATE_SPENT = (
    "Arama sınırı doldu: `graph_continue`'nun verdiği arama hakkı (Grep, Glob, fallback_rg, "
    "kabukta rg/grep/find) bitti. Çağıranlar için `graph_callers` her kullanımı satırı ve kodu "
    "ile verir. Yine de arama gerekiyorsa (ör. listenin tam olduğunu doğrulamak) tekrar dene, "
    "bu kez geçer."
)


GATE_READ = (
    "{path} büyük bir kaynak dosyası; tamamını okuma. `graph_read {path}` ana hatlarını (tip ve "
    "metotlar, satır aralıklarıyla) verir; kodu `graph_read yol::Sembol` ya da `yol:BAŞ-SON` ile "
    "oku. Düzenleyeceğin yer için Read'i offset ve en çok {lines} satırlık limit ile kullan. "
    "Tamamı gerçekten gerekiyorsa tekrar dene, bu kez geçer."
)
READ_LINES = 80  # a Read limit or a sed/head span up to this is a look at the spot to edit
READ_BYTES = 6_000  # graph_read sends a file whole up to about this size (_graph_reply.py)
READ_COMMANDS = ("cat", "bat", "nl", "less", "more", "sed", "head", "tail")
SOURCE_SUFFIXES = (".java", ".kt", ".kts", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".cs")
SOURCE_SUFFIXES += (".scala", ".groovy")
_SPAN = re.compile(r"(\d+),(\d+)p")
_COUNT = re.compile(r"(?:-n\s*|-)(\d+)\b")


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
    """Take one search from the session's budget; False once, for the first search past it."""
    with open(marker, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # parallel tool calls run their hooks at once
        text = f.read().strip()
        if text == OPEN:
            return True
        left = int(text) if text.isdigit() else DEFAULT_GREPS
        f.seek(0)
        f.truncate()
        f.write(str(left - 1) if left > 0 else OPEN)
    return left > 0


def reads(tool: str, tool_input: dict, cwd: str) -> list:
    """Large source files a Read or shell line would read whole (or more than READ_LINES of)."""
    found = []
    if tool == "Read":
        limit = tool_input.get("limit")
        if not isinstance(limit, int) or limit > READ_LINES:
            found.append(str(tool_input.get("file_path", "")))
    for part in _COMMANDS.split(str(tool_input.get("command", ""))) if tool == "Bash" else []:
        stages = part.split("|")
        words = [w.strip("'\"") for w in stages[0].split() if not re.match(r"\w+=", w)]
        name = words[0].rsplit("/", 1)[-1] if words else ""
        if name not in READ_COMMANDS or any(w[:1] in "<>" or w[:2] == "2>" for w in words):
            continue
        if name in ("cat", "bat", "nl") and len(stages) > 1:
            continue  # cat x | head: the filter decides how much
        span, count = _SPAN.search(stages[0]), _COUNT.search(stages[0])
        if name == "sed" and not (span and int(span[2]) - int(span[1]) > READ_LINES):
            continue
        if name in ("head", "tail") and not (count and int(count[1]) > READ_LINES):
            continue
        found += [w for w in words[1:] if not w.startswith("-") and not _SPAN.fullmatch(w)]
    root = Path(cwd or ".")
    return [p for p in found if Path(p).suffix in SOURCE_SUFFIXES and _large(root / p)]


def _large(path: Path) -> bool:
    try:
        return path.stat().st_size > READ_BYTES
    except OSError:
        return False


def _first_read(marker_dir: Path, session: str, paths: list) -> list:
    """paths not refused before in this session; records them as refused."""
    ledger = marker_dir / f"{session}.reads"
    with open(ledger, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        seen = set(f.read().splitlines())
        new = [p for p in dict.fromkeys(paths) if p not in seen]
        f.write("".join(f"{p}\n" for p in new))
    return new


def shell_line(command) -> str:
    """Codex's shell command as one line: an argv list joined, `bash -lc SCRIPT` unwrapped."""
    words = [str(w) for w in command] if isinstance(command, list) else None
    if words is None:
        try:
            words = shlex.split(str(command))
        except ValueError:
            return str(command)
    shells = ("bash", "sh", "zsh")
    if len(words) >= 3 and words[0].rsplit("/", 1)[-1] in shells and words[1] in ("-c", "-lc"):
        return words[2]
    return shlex.join(words) if isinstance(command, list) else str(command)


def _refuse_reads(marker_dir: Path, session: str, tool: str, tool_input: dict, cwd: str) -> int:
    whole = reads(tool, tool_input, cwd)
    refused = _first_read(marker_dir, session or "unknown", whole) if whole else []
    if refused:
        print(GATE_READ.format(path=refused[0], lines=READ_LINES), file=sys.stderr)
        return 2
    return 0


def gate(step: str, payload: str, marker_dir: Path) -> int:
    """Claude and Codex hook: exit 2 (reason on stderr) denies the tool call."""
    event = json.loads(payload or "{}")
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(event.get("session_id", "")))
    marker = marker_dir / f"{session or 'unknown'}.ok"
    cwd = str(event.get("cwd", ""))
    if step == "read":
        command = shell_line((event.get("tool_input") or {}).get("command", ""))
        marker_dir.mkdir(parents=True, exist_ok=True)
        return _refuse_reads(marker_dir, session, "Bash", {"command": command}, cwd)
    if step == "mark":
        reply = json.dumps(event.get("tool_response"))
        found = re.search(r"max_supplementary_greps\W+(\d+)", reply)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(found.group(1) if found else str(DEFAULT_GREPS))
        return 0
    tool = str(event.get("tool_name", ""))
    if tool in (GATE_FIRST, *GATE_OPEN):
        return 0
    run = re.sub(r"\D", "", os.environ.get("BIMETRI_RUN_ID", ""))
    packed = marker_dir / f"run-{run}"
    if not marker.exists() and run and packed.exists():
        marker.write_text(packed.read_text())  # the context pack ran graph_continue
    if not marker.exists():
        print(GATE_DENY.format(tool=tool), file=sys.stderr)
        return 2
    tool_input = event.get("tool_input") or {}
    command = tool_input.get("command", "") if tool == "Bash" else ""
    if (tool in SEARCH_TOOLS or searches(str(command))) and not _spend(marker):
        print(GATE_SPENT, file=sys.stderr)
        return 2
    return _refuse_reads(marker_dir, session, tool, tool_input, cwd)

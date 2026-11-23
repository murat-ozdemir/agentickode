"""bimetri patch (D2 measurement): one JSON line per graph tool call, for the dashboard.

agent-graph-mcp.sh puts this file in graph_flow.py before _graph_flow.py. The server appends to
calls/<run id>.jsonl next to graph_flow.py when it can tell the AgenticKode run: BIMETRI_RUN_ID,
which the backend exports for the agent CLI, in the server's own environment or, as Codex passes
an MCP server only a short list of variables, in an ancestor's (/proc/PID/environ, same user).
No run id, no record. The backend reads and removes the file after the agent call.

A line: ts, tool, returned (characters sent to the agent), files ({repo path: size in bytes} of
the files the answer points at; none for fallback_rg), error, over (fallback_rg past the budget).
Stdlib only.
"""

import json
import os
import re
import time
from pathlib import Path

RUN_ENV = "BIMETRI_RUN_ID"
MAX_ANCESTORS = 8
_AT = re.compile(r"(?P<rel>.+?):\d+(?:-\d+)?")  # path:LINE, path:START-END
_SITE = re.compile(r"^(?P<rel>[^\s:]+):\d+ ", re.MULTILINE)  # a graph_callers line


def _value(environ_bytes: bytes) -> str:
    key = RUN_ENV.encode() + b"="
    for item in environ_bytes.split(b"\0"):
        if item.startswith(key):
            return item[len(key) :].decode(errors="replace")
    return ""


def run_id(environ=None, proc: Path = Path("/proc"), pid: "int | None" = None) -> "str | None":
    """The run id from our environment, else from the nearest ancestor that has it."""
    value = (os.environ if environ is None else environ).get(RUN_ENV, "")
    pid = os.getppid() if pid is None else pid
    for _ in range(MAX_ANCESTORS):
        if value.isdigit() or pid <= 1:
            break
        try:
            value = _value((proc / str(pid) / "environ").read_bytes())
            stat = (proc / str(pid) / "stat").read_text()
            pid = int(stat.rsplit(")", 1)[1].split()[1])  # "pid (comm) state ppid ..."
        except (OSError, ValueError, IndexError):
            break
    return value if value.isdigit() else None


def _path(entry: str) -> str:
    rel = entry.partition("::")[0]
    at = _AT.fullmatch(rel)
    return at["rel"] if at else rel


def pointed_at(name: str, args: dict, text: str) -> list:
    """Repo paths the answer points at: the file read, the callers' files, the recommendations."""
    if name == "graph_read":
        return [_path(str(args.get("file", "")))]
    if name == "graph_callers":
        return _SITE.findall(text)
    if name == "context_pack":  # the entries whose code the pack sent
        return [_path(str(e)) for e in args.get("files", [])]
    if name == "graph_continue":
        try:
            return [_path(str(e)) for e in json.loads(text).get("recommended_files", [])]
        except (ValueError, AttributeError):
            return []
    return []


def sizes(root: Path, paths: list) -> dict:
    out = {}
    for rel in dict.fromkeys(p for p in paths if p):
        path = (root / rel).resolve()
        if path.is_relative_to(root) and path.is_file():
            out[rel] = path.stat().st_size
    return out


class Recorder:
    """Appends a line per call to out_dir/<run>.jsonl; does nothing without a run id."""

    def __init__(self, root: Path, run: "str | None", out_dir: Path) -> None:
        self.root, self.run, self.out_dir = root, run, out_dir

    def __call__(self, name: str, args: dict, text: str, error: bool) -> None:
        if not self.run:
            return
        line = {
            "ts": round(time.time(), 3),
            "tool": name,
            "returned": len(text),
            "files": {} if error else sizes(self.root, pointed_at(name, args, text)),
            "error": bool(error),
            "over": name == "fallback_rg" and "(over graph_continue's" in text,
        }
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            with open(self.out_dir / f"{self.run}.jsonl", "a") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            pass  # measurement only: never fail the tool call

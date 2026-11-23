"""bimetri patch (graf tasarruf planı, Faz 1): the graph_read reply.

agent-graph-mcp.sh puts this file after _graph_read.py in graph_flow.py. A reply is at most
READ_CHARS. A file larger than that comes as an outline (its types and methods with their line
ranges); the code is then read with `path::Symbol` or `path:START-END`. `read_part` also returns
the line ranges it sent, for the run's dedupe (_graph_budget.py).
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from _graph_read import _NOT_DECL, SYMBOL_LINES, _code_only, block_end, declarations  # bundle: drop

READ_CHARS = 6_000
WINDOW_LINES = 10  # graph_read path:LINE shows this many lines on each side
_LOCATION = re.compile(r"(?P<rel>.+?):(?P<start>\d+)(?:-(?P<end>\d+))?")
_DECL = re.compile(
    r"\b(?:class|interface|enum|record|@interface)\s+(?P<t>\w+)|[\w>\]?]\s+(?P<m>\w+)\s*\("
)
_KEYWORDS = {"if", "for", "while", "switch", "catch", "synchronized", "return", "new", "throw"}


def _end(lines: list, start: int, python: bool) -> int:
    if not python:
        return block_end(lines, start)
    indent = len(lines[start]) - len(lines[start].lstrip())
    last = start
    for i in range(start + 1, min(len(lines), start + SYMBOL_LINES)):
        if lines[i].strip():
            if len(lines[i]) - len(lines[i].lstrip()) <= indent:
                break
            last = i
    return last


def outline(lines: list, rel: str) -> str:
    """Types and methods of a large file with their line ranges, at most READ_CHARS."""
    rows, in_comment, python = [], False, rel.endswith(".py")
    for i, text in enumerate(lines):
        code, in_comment = _code_only(text, in_comment)
        match = _DECL.search(code)
        group = "t" if match and match["t"] else "m"
        if match is None or match[group] in _KEYWORDS:
            continue
        if _NOT_DECL.search(code[: match.start(group)]):
            continue
        signature = text.strip().removesuffix("{").strip()[:120]
        rows.append(f"{i + 1}-{_end(lines, i, python) + 1}: {signature}")
    head = f"{rel}: {len(lines)} lines, outline; read code with {rel}::Name or {rel}:START-END"
    if not rows:
        return ""
    text, shown = head, 0
    for row in rows:
        if len(text) + len(row) + 1 > READ_CHARS:
            break
        text, shown = f"{text}\n{row}", shown + 1
    more = len(rows) - shown
    return text + (f"\n... {more} more declarations" if more else "")


def _numbered(lines: list, start: int, end: int) -> str:
    return "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))


@dataclass
class Part:
    """One graph_read answer: the text and the 1-based line ranges of the code it holds."""

    rel: str
    stamp: tuple
    text: str
    ranges: list = field(default_factory=list)


def _cap(rel: str, lines: list, ranges: list) -> tuple:
    """Numbered text of the ranges, cut at READ_CHARS; (text, ranges actually sent)."""
    parts, sent, size = [], [], 0
    for start, end in ranges:
        body = [f"{rel}:{start}-{end}"]
        for i in range(start - 1, end):
            row = f"{i + 1}: {lines[i]}"
            if size + len(row) > READ_CHARS and (sent or len(body) > 1):
                if len(body) > 1:
                    parts.append("\n".join(body))
                    sent.append((start, i))
                parts.append(f"... cut at {READ_CHARS} chars; read {rel}:{i + 1}-{end} next")
                return "\n\n".join(parts), sent
            body.append(row)
            size += len(row) + 1
        parts.append("\n".join(body))
        sent.append((start, end))
    return "\n\n".join(parts), sent


def read_part(root: Path, target: str) -> "Part | str":
    """graph_read: a file (whole if small, else its outline), `file::Symbol` (each declaration),
    or `file:LINE` / `file:START-END` (a window around a line, or a range). A str is an error."""
    rel, _, symbol = target.partition("::")
    where = None if symbol else _LOCATION.fullmatch(rel)
    rel = where["rel"] if where else rel
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return f"no such file in the clone: {rel}"
    info = path.stat()
    stamp = (info.st_mtime_ns, info.st_size)
    lines = path.read_text(errors="replace").splitlines()
    if where:
        line = int(where["start"])
        start, end = (
            (line - 1, int(where["end"]))
            if where["end"]
            else (line - 1 - WINDOW_LINES, line + WINDOW_LINES)
        )
        start, end = max(start, 0), min(end, len(lines), max(start, 0) + SYMBOL_LINES)
        if start >= end:
            return f"{rel} has {len(lines)} lines"
        return Part(rel, stamp, *_cap(rel, lines, [(start + 1, end)]))
    if not symbol:
        whole = _numbered(lines, 0, len(lines))
        if len(whole) <= READ_CHARS:
            return Part(rel, stamp, whole, [(1, len(lines))] if lines else [])
        summary = outline(lines, rel)
        if summary:
            return Part(rel, stamp, summary)
        text, sent = _cap(rel, lines, [(1, len(lines))])
        return Part(rel, stamp, text, sent)
    name = symbol.split(".")[-1].removesuffix("()")
    ranges, covered = [], -1
    for start in declarations(lines, name)[:4]:
        if start <= covered:
            continue  # a constructor inside the class block already shown
        covered = _end(lines, start, rel.endswith(".py"))
        ranges.append((start + 1, covered + 1))
    if not ranges:
        return f"{name} is not declared in {rel}; read {rel} for its outline"
    return Part(rel, stamp, *_cap(rel, lines, ranges))


def read(root: Path, target: str) -> str:
    part = read_part(root, target)
    return part if isinstance(part, str) else part.text

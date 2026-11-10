"""bimetri patch (D2 phase 2): source reading for the graph flow (graph_read, use-site lines).

agent-graph-mcp.sh puts this file first in graph_flow.py. Run #95 showed the cost of reading a
whole enclosing method to see a one-line call site, so use sites are shown as their statement
(statement) and graph_read takes `path:LINE` for a small window around a line.
"""

import re
from pathlib import Path

FILE_LINES = 400
SYMBOL_LINES = 250
WINDOW_LINES = 10  # graph_read path:LINE shows this many lines on each side
USE_LINES = 4  # a use-site statement spans at most this many lines
USE_WIDTH = 220
_LITERAL = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])'|//.*$")
_NOT_DECL = re.compile(r"\b(?:return|new|throw|else|yield|await)\s+$")
_LOCATION = re.compile(r"(?P<rel>.+?):(?P<start>\d+)(?:-(?P<end>\d+))?")


def _code_only(text: str, in_comment: bool) -> tuple:
    """text without string literals and comments, and whether a /* comment is still open."""
    text, out = _LITERAL.sub('""', text), ""
    while text:
        if in_comment:
            end = text.find("*/")
            text, in_comment = ("", True) if end < 0 else (text[end + 2 :], False)
        else:
            begin = text.find("/*")
            if begin < 0:
                return out + text, False
            out, text, in_comment = out + text[:begin], text[begin + 2 :], True
    return out, in_comment


def block_end(lines: list, start: int) -> int:
    """Last line (0-based) of the declaration at lines[start]: its brace block, or up to `;`."""
    depth, opened, in_comment = 0, False, False
    stop = min(len(lines), start + SYMBOL_LINES)
    for i in range(start, stop):
        text, in_comment = _code_only(lines[i], in_comment)
        if not opened and ";" in text.split("{", 1)[0]:
            return i  # abstract/interface method or field
        depth += text.count("{") - text.count("}")
        opened = opened or "{" in text
        if opened and depth <= 0:
            return i
    return stop - 1


def declarations(lines: list, name: str) -> list:
    """0-based lines that declare name: a type, or a method/constructor after a type or modifier."""
    word = re.escape(name)
    kind = re.compile(rf"\b(?:class|interface|enum|record|@interface)\s+(?P<n>{word})\b")
    method = re.compile(rf"[\w>\]?]\s+(?P<n>{word})\s*\(")
    found, in_comment = [], False
    for i, text in enumerate(lines):
        code, in_comment = _code_only(text, in_comment)
        match = kind.search(code) or method.search(code)
        if match and not _NOT_DECL.search(code[: match.start("n")]):
            found.append(i)
    return found


def statement(lines: list, line: int) -> str:
    """The statement that starts at 1-based line, on one line: until its parentheses close."""
    if not 0 < line <= len(lines):
        return ""
    parts, depth, in_comment = [], 0, False
    for text in lines[line - 1 : line - 1 + USE_LINES]:
        code, in_comment = _code_only(text, in_comment)
        parts.append(text.strip())
        depth += code.count("(") - code.count(")")
        if depth <= 0:
            break
    text = " ".join(parts)
    return text if len(text) <= USE_WIDTH else text[: USE_WIDTH - 3] + "..."


def _numbered(lines: list, start: int, end: int) -> str:
    return "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))


def read(root: Path, target: str) -> str:
    """graph_read: a file (first FILE_LINES lines), `file::Symbol` (each declaration), or
    `file:LINE` / `file:START-END` (a window around a line, or a range)."""
    rel, _, symbol = target.partition("::")
    where = None if symbol else _LOCATION.fullmatch(rel)
    rel = where["rel"] if where else rel
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return f"no such file in the clone: {rel}"
    lines = path.read_text(errors="replace").splitlines()
    if where:
        line = int(where["start"])
        start, end = (
            (line - 1, int(where["end"]))
            if where["end"]
            else (line - 1 - WINDOW_LINES, line + WINDOW_LINES)
        )
        start, end = max(start, 0), min(end, len(lines), max(start, 0) + SYMBOL_LINES)
        return (
            f"{rel}:{start + 1}-{end}\n{_numbered(lines, start, end)}"
            if start < end
            else f"{rel} has {len(lines)} lines"
        )
    if not symbol:
        rest = len(lines) - FILE_LINES
        more = f"\n... {rest} more lines; read a symbol with file::Name" if rest > 0 else ""
        return _numbered(lines, 0, min(len(lines), FILE_LINES)) + more
    name = symbol.split(".")[-1].removesuffix("()")
    parts, covered = [], -1
    for start in declarations(lines, name)[:4]:
        if start <= covered:
            continue  # a constructor inside the class block already shown
        covered = block_end(lines, start)
        parts.append(f"{rel}:{start + 1}-{covered + 1}\n{_numbered(lines, start, covered + 1)}")
    return "\n\n".join(parts) or f"{name} is not declared in {rel}; read the file instead"


class Sources:
    """Use-site statements, each file read once per tool call."""

    def __init__(self, root: Path | None) -> None:
        self.root, self.files = root, {}

    def at(self, rel: str, line: int) -> str:
        if self.root is None or not line:
            return ""
        if rel not in self.files:
            path = (self.root / rel).resolve()
            ok = path.is_relative_to(self.root) and path.is_file()
            self.files[rel] = path.read_text(errors="replace").splitlines() if ok else []
        return statement(self.files[rel], line)

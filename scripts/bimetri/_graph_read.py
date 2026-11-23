"""bimetri patch (D2 phase 2): source reading for the graph flow (graph_read, use-site lines).

agent-graph-mcp.sh puts this file first in graph_flow.py. Run #95 showed the cost of reading a
whole enclosing method to see a one-line call site, so use sites are shown as their statement
(statement). The graph_read reply itself (path:LINE window, outline, character cap) is in
_graph_reply.py.
"""

import re
from pathlib import Path

SYMBOL_LINES = 250
USE_LINES = 4  # a use-site statement spans at most this many lines
USE_WIDTH = 220
_LITERAL = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])'|//.*$")
_NOT_DECL = re.compile(r"\b(?:return|new|throw|else|yield|await)\s+$|->\s*$")


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

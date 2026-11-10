"""bimetri patch (D2 phase 2): the agents' context flow over Graphify's graph.json.

Modelled on GrapeRoot's Dual-Graph flow (graph_continue first, then capped fallbacks), over
Graphify's graph, whose Java edges reach the calling files (Phase 1c). Served by
_graph_flow_server.py; no networkx import here.
"""

import re
from pathlib import Path

USE_RELATIONS = ("calls", "references", "implements", "inherits", "imports")
MAX_NAMES = 30
MAX_SEEDS_PER_NAME = 2
MAX_RECOMMENDED = 15
FILE_LINES = 400
SYMBOL_LINES = 250
OUTPUT_LINES = 80  # graph_callers and fallback_rg
# confidence -> (fallback_rg calls, extra files to read) allowed before writing code.
CAPS = {"high": (1, 2), "medium": (2, 3), "low": (4, 5)}
# Names worth a lookup: camelCase/PascalCase with an inner capital, snake_case, or name(.
_NAME = re.compile(r"\b[A-Za-z_]\w*(?=\()|\b[A-Za-z_]*[a-z0-9][A-Z_]\w*")
_WORD = re.compile(r"\b[A-Z][a-z0-9]{3,}\b")  # Device, Gateway: only if the graph has it
_PATH = re.compile(r"[\w./-]+\.(?:java|kt|py|ts|tsx|js|xml|sql|ya?ml|properties)\b")
_LITERAL = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])'|//.*$")
_NOT_DECL = re.compile(r"\b(?:return|new|throw|else|yield|await)\s+$")


def norm(label: str) -> str:
    return label.strip().lstrip(".").removesuffix("()").lower()


def code_nodes(graph) -> dict:
    """norm(label) -> node ids, code nodes only."""
    index: dict = {}
    for nid, data in graph.nodes(data=True):
        if data.get("file_type") == "code" and data.get("label"):
            index.setdefault(norm(data["label"]), []).append(nid)
    return index


def line_of(location) -> int:
    match = re.match(r"L(\d+)", str(location or ""))
    return int(match.group(1)) if match else 0


def entry(graph, nid: str) -> str:
    """`path` for file nodes and the class named after its file, else `path::Symbol`."""
    data = graph.nodes[nid]
    path, name = data.get("source_file", ""), norm(data.get("label", ""))
    if not name or name in (Path(path).name.lower(), Path(path).stem.lower()):
        return path
    return f"{path}::{data['label'].strip().lstrip('.').removesuffix('()')}"


def users(graph, nid: str):
    """(user node, relation, use-site line) for each edge into nid."""
    for src, _dst, data in graph.in_edges(nid, data=True):
        if data.get("relation") in USE_RELATIONS and src != nid:
            yield src, data["relation"], line_of(data.get("source_location"))


def find_seeds(graph, index: dict, task: str) -> tuple:
    """(seed ids, names missing from the graph, names with too many matches)."""
    names = list(dict.fromkeys(_NAME.findall(task)))[:MAX_NAMES]
    words = [w for w in dict.fromkeys(_WORD.findall(task)) if norm(w) in index and w not in names]
    hits = {name: index.get(norm(name), []) for name in names + words[:MAX_NAMES]}
    unique = {graph.nodes[ids[0]]["source_file"] for ids in hits.values() if len(ids) == 1}
    seeds, missing, ambiguous = [], [], []
    for name, ids in hits.items():
        if not ids:
            missing += [name] if any(c.isupper() for c in name[1:]) else []
            continue
        near = [n for n in ids if graph.nodes[n]["source_file"] in unique] or ids
        if len(near) > MAX_SEEDS_PER_NAME:
            ambiguous.append(name)
        seeds += near[:MAX_SEEDS_PER_NAME]
    return list(dict.fromkeys(seeds)), missing, ambiguous


def continue_flow(graph, task: str, root: Path, fallback=None) -> dict:
    """graph_continue: the files to read for task, how sure that is, and the caps that follow."""
    seeds, missing, ambiguous = find_seeds(graph, code_nodes(graph), task)
    paths = [p for p in dict.fromkeys(_PATH.findall(task)) if (root / p).is_file()]
    confidence = "high" if (seeds or paths) and not missing and not ambiguous else "medium"
    if not seeds and not paths:
        seeds, confidence = (fallback(task) if fallback else [])[:3], "low"
    why = dict.fromkeys(paths, "named in the task")
    for nid in seeds:
        why.setdefault(entry(graph, nid), "named in the task")
    more = 0
    # Method seeds first: their callers are closer to the task than the class's users.
    for nid in sorted(seeds, key=lambda n: not graph.nodes[n]["label"].endswith("()")):
        for src, relation, line in users(graph, nid):
            item = entry(graph, src)
            if item in why:
                continue
            if len(why) >= MAX_RECOMMENDED:
                more += 1
                continue
            why[item] = f"{relation} {graph.nodes[nid]['label']} at L{line}"
    greps, files = CAPS[confidence]
    result = {
        "confidence": confidence,
        "recommended_files": list(why),
        "why": why,
        "max_supplementary_greps": greps,
        "max_supplementary_files": files,
    }
    if missing or ambiguous:
        result.update(not_in_graph=missing, ambiguous=ambiguous)
    if more:
        result["more_users"] = f"{more} more; graph_callers lists them all"
    return result


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


def read(root: Path, target: str) -> str:
    """graph_read: a file (first FILE_LINES lines) or `file::Symbol` (each declaration)."""
    rel, _, symbol = target.partition("::")
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return f"no such file in the clone: {rel}"
    lines = path.read_text(errors="replace").splitlines()
    if not symbol:
        out = "\n".join(f"{i + 1}: {t}" for i, t in enumerate(lines[:FILE_LINES]))
        rest = len(lines) - FILE_LINES
        return out + (f"\n... {rest} more lines; read a symbol with file::Name" if rest > 0 else "")
    name = symbol.split(".")[-1].removesuffix("()")
    parts, covered = [], -1
    for start in declarations(lines, name)[:4]:
        if start <= covered:
            continue  # a constructor inside the class block already shown
        covered = block_end(lines, start)
        body = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, covered + 1))
        parts.append(f"{rel}:{start + 1}-{covered + 1}\n{body}")
    return "\n\n".join(parts) or f"{name} is not declared in {rel}; read the file instead"


def callers(graph, target: str) -> str:
    """graph_callers: every use of `Symbol` or `file::Symbol`, with the use-site line."""
    rel, _, name = target.rpartition("::")
    key = norm(name.split(".")[-1] if "." in name.removesuffix("()") else name)
    ids = [
        n for n in code_nodes(graph).get(key, []) if not rel or graph.nodes[n]["source_file"] == rel
    ]
    if not ids:
        return f"{name} is not in the graph"
    out = sorted(
        {
            f"{graph.nodes[src]['source_file']}:{line} {graph.nodes[src].get('label', '')} {relation} "
            f"{graph.nodes[nid].get('label', '')}"
            for nid in ids
            for src, relation, line in users(graph, nid)
        }
    )
    cut = [f"... {len(out) - OUTPUT_LINES} more"] if len(out) > OUTPUT_LINES else []
    return "\n".join(out[:OUTPUT_LINES] + cut) or f"nothing in the graph uses {name}"

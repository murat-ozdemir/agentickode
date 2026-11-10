"""bimetri patch (D2 phase 2): the agents' context flow over Graphify's graph.json.

Modelled on GrapeRoot's Dual-Graph flow (graph_continue first, then capped fallbacks), over
Graphify's graph, whose Java edges reach the calling files (Phase 1c). Use sites come with their
statement (run #95: reading whole methods for one-line call sites cost 2x). Served by
_graph_flow_server.py; no networkx import here.
"""

import re
from pathlib import Path

from _graph_read import Sources  # bundle: drop

USE_RELATIONS = ("calls", "references", "implements", "inherits", "imports")
MAX_NAMES = 30
MAX_SEEDS_PER_NAME = 2
MAX_RECOMMENDED = 15
OUTPUT_LINES = 80  # graph_callers and fallback_rg
# confidence -> (fallback_rg calls, extra files to read) allowed before writing code.
CAPS = {"high": (1, 2), "medium": (2, 3), "low": (4, 5)}
# Names worth a lookup: camelCase/PascalCase with an inner capital, snake_case, or name(.
_NAME = re.compile(r"\b[A-Za-z_]\w*(?=\()|\b[A-Za-z_]*[a-z0-9][A-Z_]\w*")
_WORD = re.compile(r"\b[A-Z][a-z0-9]{3,}\b")  # Device, Gateway: only if the graph has it
_PATH = re.compile(r"[\w./-]+\.(?:java|kt|py|ts|tsx|js|xml|sql|ya?ml|properties)\b")
SITE_RELATIONS = ("calls", "references")  # recommended as path:LINE, not the whole caller


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
    more, sources = 0, Sources(root)
    # Method seeds first: their callers are closer to the task than the class's users.
    for nid in sorted(seeds, key=lambda n: not graph.nodes[n]["label"].endswith("()")):
        for src, relation, line in users(graph, nid):
            rel = graph.nodes[src].get("source_file", "")
            site = relation in SITE_RELATIONS and line
            item = f"{rel}:{line}" if site else entry(graph, src)
            if item in why:
                continue
            if len(why) >= MAX_RECOMMENDED:
                more += 1
                continue
            why[item] = f"{relation} {graph.nodes[nid]['label']} at L{line}"
            code = sources.at(rel, line) if site else ""
            why[item] += f": {code}" if code else ""
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


def _owned_by(source_file: str, owner: str) -> bool:
    """owner is the node's file path, or its class: the file stem (Class::method, Class.method)."""
    return not owner or owner in (source_file, Path(source_file).stem)


def callers(graph, target: str, root: Path | None = None) -> str:
    """graph_callers: every use of `Symbol`, `Class.Symbol`, `Class::Symbol` or `file::Symbol`,
    with the use-site line and, given the clone root, its statement."""
    owner, _, name = target.rpartition("::")
    head, _, last = name.removesuffix("()").rpartition(".")
    owner = owner or head
    ids = [
        n
        for n in code_nodes(graph).get(norm(last), [])
        if _owned_by(graph.nodes[n]["source_file"], owner)
    ]
    if not ids:
        return f"{name} is not in the graph"
    sources, out = Sources(root), set()
    for nid in ids:
        for src, relation, line in users(graph, nid):
            rel = graph.nodes[src]["source_file"]
            code = sources.at(rel, line)
            text = f"{rel}:{line} {graph.nodes[src].get('label', '')} {relation} "
            text += graph.nodes[nid].get("label", "") + (f": {code}" if code else "")
            out.add((rel, line, text))
    out = [text for _rel, _line, text in sorted(out)]
    cut = [f"... {len(out) - OUTPUT_LINES} more"] if len(out) > OUTPUT_LINES else []
    return "\n".join(out[:OUTPUT_LINES] + cut) or f"nothing in the graph uses {name}"

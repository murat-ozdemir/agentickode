"""bimetri patch (graf tasarruf planı, Faz 2): the context pack, graph_continue run for the agent.

agent-graph-mcp.sh puts this file after _graph_flow.py in graph_flow.py. Before the agent call the
backend runs `agent_graph.py pack graphify ROOT` (task on stdin), which runs
    python -I graph_flow.py GRAPH_JSON ROOT --pack
and prints the pack: graph_continue's answer and the code of its first entries, at most PACK_CHARS.
The prompt carries it, so the agent's first exploring turns (graph_continue, then a graph_read per
entry) are not needed. For the same run id it also writes:
    pack/<run>.json     what the pack sent; the MCP server marks it sent (_graph_budget.py dedupe)
                        and takes its grep budget, so fallback_rg works without graph_continue
    gate/run-<run>      the grep budget; the Claude gate opens on it as after graph_continue
No graph yet, or any failure: prints nothing, the agent runs the flow itself.
"""

# ruff: noqa: RUF001 - the pack text is Turkish; dotless i is a letter there

import json
import time
from pathlib import Path

from _graph_flow import callers, continue_flow  # bundle: drop
from _graph_reply import read_part  # bundle: drop

PACK_CHARS = 15_000
PACK_BODIES = 5
CALLER_LINES = 12
KEEP_DAYS = 2  # old pack/ and gate/run-* files are removed when a new pack is written
HEAD = (
    "## Kod grafiği bağlam paketi\n"
    "Platform bu çağrıdan önce `graph_continue`'yu görev metniyle çalıştırdı; sonucu ve önerilen "
    "kodun bir kısmı aşağıda. Bu görev için `graph_continue`'yu yeniden çağırma, aşağıdaki kodu "
    "`graph_read` ile yeniden okuma. Eksik kalan yer için `graph_read yol::Sembol` ya da "
    "`yol:BAŞ-SON` kullan. Arama hakkı: {greps} `fallback_rg`, ek dosya: {files}."
)


def _entries(result: dict) -> list:
    why = result.get("why") or {}
    return [f"- {e}" + (f": {why[e]}" if why.get(e) else "") for e in result["recommended_files"]]


def build(graph, task: str, root: Path, score=None) -> tuple:
    """(pack text, record of what it sent) for one task; text "" when nothing was recommended."""
    result = continue_flow(graph, task, root, score)
    greps, files = result["max_supplementary_greps"], result["max_supplementary_files"]
    entries = result["recommended_files"]
    sent = {"greps": greps, "ranges": [], "outlines": [], "callers": [], "files": []}
    if not entries:
        return "", sent
    parts = [HEAD.format(greps=greps, files=files)]
    parts.append(f"Güven: {result['confidence']}. Öneriler:\n" + "\n".join(_entries(result)))
    size, bodies = sum(len(p) for p in parts), 0
    symbol_files = {e.partition("::")[0] for e in entries if "::" in e}
    for entry in entries:
        if bodies >= PACK_BODIES:
            break
        part = read_part(root, entry)
        if isinstance(part, str) or (not part.ranges and part.rel in symbol_files):
            continue  # an error, or the outline of a file whose symbol is in the list
        if size + len(part.text) > PACK_CHARS:
            continue
        parts.append(f"### {entry}\n{part.text}")
        size, bodies = size + len(part.text), bodies + 1
        stamp = list(part.stamp)
        sent["files"].append(entry)
        if part.ranges:
            sent["ranges"] += [[part.rel, *stamp, s, e] for s, e in part.ranges]
        else:
            sent["outlines"].append([part.rel, *stamp])
    for entry in [e for e in entries if "::" in e][:2]:
        symbol = entry.partition("::")[2]
        lines = callers(graph, entry, root).splitlines()
        text = "\n".join(lines[:CALLER_LINES])
        if len(lines) > CALLER_LINES:
            text += f"\n... {len(lines) - CALLER_LINES} more: graph_callers {entry}"
        if lines and not text.endswith("is not in the graph") and size + len(text) <= PACK_CHARS:
            parts.append(f"### {symbol} çağıranlar\n{text}")
            size += len(text)
            sent["callers"].append(entry)
    return "\n\n".join(parts), sent


def _tidy(folder: Path, pattern: str) -> None:
    cutoff = time.time() - KEEP_DAYS * 86_400
    for old in folder.glob(pattern):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass


def save(base: Path, run: "str | None", sent: dict) -> None:
    """pack/<run>.json and gate/run-<run>; nothing without a run id."""
    if not run:
        return
    for folder, name, text in (
        (base / "pack", f"{run}.json", json.dumps(sent, ensure_ascii=False)),
        (base / "gate", f"run-{run}", str(sent["greps"])),
    ):
        folder.mkdir(parents=True, exist_ok=True)
        _tidy(folder, "*.json" if folder.name == "pack" else "run-*")
        (folder / name).write_text(text)


def adopt(ledger, pack_file: Path) -> "int | None":
    """Mark what the run's pack sent as sent by call 0; the pack's grep budget, None if none."""
    try:
        sent = json.loads(pack_file.read_text())
    except (OSError, ValueError):
        return None
    for rel, mtime, size, start, end in sent.get("ranges", []):
        ledger.lines.setdefault((rel, (mtime, size)), []).append((start, end, 0))
    for rel, mtime, size in sent.get("outlines", []):
        ledger.first[(rel, (mtime, size), "outline")] = 0
    for symbol in sent.get("callers", []):
        ledger.first[("callers", symbol)] = 0
    greps = sent.get("greps")
    return greps if isinstance(greps, int) else None

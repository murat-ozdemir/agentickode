"""bimetri patch (D2 phase 2): stdio MCP server for the _graph_flow.py tools.

agent-graph-mcp.sh appends this file to _graph_flow.py (dropping the `# bundle: drop` lines) and
installs the result as graph_flow.py; serve runs it with the Graphify venv's python (-I):
    python -I graph_flow.py GRAPH_JSON ROOT
    python -I graph_flow.py GRAPH_JSON ROOT --pack     (task on stdin; prints the context pack)
Uses Graphify's private loader and scorer (graphify.serve), pinned by the Graphify lock file.
The graph is reloaded whenever graph.json changes on disk. Before the first build there is no
graph.json: the server still answers, and graph_continue says so with the low-confidence caps.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from _graph_budget import Ledger  # bundle: drop
from _graph_calls import Recorder, run_id  # bundle: drop
from _graph_flow import CAPS, OUTPUT_LINES, callers, continue_flow  # bundle: drop
from _graph_pack import adopt, build, save  # bundle: drop
from _graph_reply import read_part  # bundle: drop

TOOLS = {
    "graph_continue": (
        "Call first per task (skip if the prompt has the context pack). Returns recommended "
        "entries with why, confidence and the fallback_rg / extra file caps.",
        {"task": "the task with the class/method names it involves"},
    ),
    "graph_read": (
        "Read an entry: path (large files as an outline), path::Symbol, path:LINE or "
        "path:START-END. 6k chars per answer, 60k per agent call; no resends.",
        {"file": "repo-relative path, optionally ::Symbol or :LINE"},
    ),
    "graph_callers": (
        "Every use of a symbol with file, line and statement.",
        {"symbol": "Symbol, Class.Symbol or path::Symbol"},
    ),
    "fallback_rg": (
        "ripgrep in the clone; keep to max_supplementary_greps.",
        {"pattern": "ripgrep regex", "glob": "optional glob, e.g. *.java"},
    ),
}
BUILDING = (
    "the graph of this clone is still being built; use graph_read and fallback_rg within the caps"
)
REQUIRED = {
    "graph_continue": "task",
    "graph_read": "file",
    "graph_callers": "symbol",
    "fallback_rg": "pattern",
}


class Flow:
    """The tools' state: the loaded graph, the grep budget of the last graph_continue and the
    reading budget of this agent call."""

    def __init__(self, graph_path: Path, root: Path, load, score) -> None:
        self.graph_path, self.root, self.load, self.score = graph_path, root, load, score
        self.loaded: Any = None
        self.stamp, self.greps = None, None
        self.ledger = Ledger()

    def graph(self):
        if not self.graph_path.exists():
            raise RuntimeError(BUILDING)
        stamp = self.graph_path.stat().st_mtime_ns
        if stamp != self.stamp:
            self.loaded, self.stamp = self.load(str(self.graph_path)), stamp
        return self.loaded

    def call(self, name: str, args: dict) -> tuple:
        """(text, is_error) for one tool call."""
        if not str(args.get(REQUIRED.get(name, ""), "")).strip():
            return f"{name} needs `{REQUIRED.get(name)}`", True
        if name == "graph_continue" and not self.graph_path.exists():
            greps, files = CAPS["low"]
            self.greps = greps
            result = {"confidence": "low", "recommended_files": [], "note": BUILDING}
            result.update(max_supplementary_greps=greps, max_supplementary_files=files)
            return json.dumps(result, ensure_ascii=False, indent=1), False
        if name == "graph_continue":
            graph = self.graph()
            result = continue_flow(graph, args["task"], self.root, lambda t: self.score(graph, t))
            result["graph_commit"] = graph.graph.get("built_at_commit", "")
            self.greps = result["max_supplementary_greps"]
            return json.dumps(result, ensure_ascii=False, indent=1), False
        if name == "graph_read":
            return self.read(str(args["file"])), False
        if name == "graph_callers":
            symbol = str(args["symbol"])
            key = ("callers", symbol)
            note = self.ledger.repeat(symbol, key)
            return note or self.ledger.send(callers(self.graph(), symbol, self.root), key), False
        if name == "fallback_rg":
            if self.greps is None:
                return "call graph_continue first", True
            self.greps -= 1  # over budget it still runs (run #95): a note, not a refusal
            note = "\n(over graph_continue's max_supplementary_greps)" if self.greps < 0 else ""
            return rg(self.root, args["pattern"], str(args.get("glob", ""))) + note, False
        return f"unknown tool {name}", True

    def read(self, target: str) -> str:
        part = read_part(self.root, target)
        if isinstance(part, str):
            return part
        if part.ranges:
            key, ranges = (part.rel, part.stamp), part.ranges
        else:  # an outline
            key, ranges = (part.rel, part.stamp, "outline"), None
        note = self.ledger.repeat(target, key, ranges)
        return note or self.ledger.send(part.text, key, ranges)


def rg(root: Path, pattern: str, glob: str = "") -> str:
    """fallback_rg: ripgrep in the clone, at most 5 matches per file and OUTPUT_LINES in all."""
    command = ["rg", "-n", "--no-heading", "-m", "5", "-e", pattern]
    command += ["-g", glob] if glob else []
    try:
        done = subprocess.run([*command, "."], cwd=root, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return "rg timed out; narrow the pattern or add a glob"
    lines = done.stdout.splitlines()
    cut = [f"... {len(lines) - OUTPUT_LINES} more lines"] if len(lines) > OUTPUT_LINES else []
    return "\n".join(lines[:OUTPUT_LINES] + cut) or (done.stderr.strip() or "no match")


def scorer(score_nodes, query_terms):
    """Graphify's own ranking, code nodes only, for tasks that name nothing in the graph."""

    def score(graph, task: str) -> list:
        ranked = sorted(score_nodes(graph, query_terms(task)), reverse=True)
        return [nid for _s, nid in ranked if graph.nodes[nid].get("file_type") == "code"]

    return score


def build_server(flow: Flow, record=None):
    from mcp import types  # pyright: ignore[reportMissingImports]
    from mcp.server import Server  # pyright: ignore[reportMissingImports]

    def schema(params: dict, required: str) -> dict:
        props = {key: {"type": "string", "description": text} for key, text in params.items()}
        return {"type": "object", "properties": props, "required": [required]}

    tools = [
        types.Tool(name=name, description=text, inputSchema=schema(params, REQUIRED[name]))
        for name, (text, params) in TOOLS.items()
    ]

    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(ctx, params) -> types.CallToolResult:
        try:
            text, error = flow.call(params.name, dict(params.arguments or {}))
        except Exception as exc:  # report, keep serving
            text, error = f"{params.name} failed: {exc}", True
        if record:  # calls/<run>.jsonl for the dashboard (_graph_calls.py)
            record(params.name, dict(params.arguments or {}), text, error)
        content = [types.TextContent(type="text", text=text)]
        return types.CallToolResult(content=content, isError=error)

    return Server(
        "bimetri-graph", version="1", on_list_tools=on_list_tools, on_call_tool=on_call_tool
    )


def pack(flow: Flow, task: str, record, base: Path, run: "str | None") -> int:
    """Print the context pack for task (_graph_pack.py); prints nothing without a graph."""
    if not flow.graph_path.exists() or not task.strip():
        return 0
    graph = flow.graph()
    text, sent = build(graph, task, flow.root, lambda t: flow.score(graph, t))
    if text:
        save(base, run, sent)
        record("context_pack", {"files": sent["files"]}, text, False)
        print(text)
    return 0


def main(graph_path: Path, root: Path, mode: str = "") -> int:
    import anyio
    from graphify.serve import (  # pyright: ignore[reportMissingImports]
        _load_graph,
        _query_terms,
        _score_nodes,
    )
    from mcp.server.stdio import stdio_server  # pyright: ignore[reportMissingImports]

    flow = Flow(graph_path, root, _load_graph, scorer(_score_nodes, _query_terms))
    base, run = Path(__file__).resolve().parent, run_id()
    record = Recorder(root, run, base / "calls")
    if mode == "--pack":
        return pack(flow, sys.stdin.read(), record, base, run)
    if graph_path.exists():
        flow.graph()
    if run:  # what the run's context pack already sent, and its grep budget
        flow.greps = adopt(flow.ledger, base / "pack" / f"{run}.json")
    server = build_server(flow, record)

    async def run() -> None:
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    anyio.run(run)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]).resolve(), *sys.argv[3:4]))

"""bimetri patch (D2 phase 2): stdio MCP server for the _graph_flow.py tools.

agent-graph-mcp.sh appends this file to _graph_flow.py (dropping the `# bundle: drop` lines) and
installs the result as graph_flow.py; serve runs it with the Graphify venv's python (-I):
    python -I graph_flow.py GRAPH_JSON ROOT
Uses Graphify's private loader and scorer (graphify.serve), pinned by the Graphify lock file.
The graph is reloaded whenever graph.json changes on disk.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from _graph_flow import OUTPUT_LINES, callers, continue_flow, read  # bundle: drop

TOOLS = {
    "graph_continue": (
        "Call first, once per task or subtask. Returns recommended_files (path or path::Symbol) "
        "with why each matters, confidence, and how many fallback_rg calls / extra files the "
        "task allows.",
        {"task": "the task in your own words, with the class/method names it involves"},
    ),
    "graph_read": (
        "Read one recommended file, or only one symbol's lines with path::Symbol.",
        {"file": "repo-relative path, optionally ::Symbol"},
    ),
    "graph_callers": (
        "Every call, reference, implementation and import of a symbol, with file and line.",
        {"symbol": "Symbol or path::Symbol"},
    ),
    "fallback_rg": (
        "ripgrep in the clone, only after graph_continue and within its max_supplementary_greps.",
        {"pattern": "a ripgrep regex", "glob": "optional file glob, e.g. *.java"},
    ),
}
REQUIRED = {
    "graph_continue": "task",
    "graph_read": "file",
    "graph_callers": "symbol",
    "fallback_rg": "pattern",
}


class Flow:
    """The tools' state: the loaded graph and the grep budget of the last graph_continue."""

    def __init__(self, graph_path: Path, root: Path, load, score) -> None:
        self.graph_path, self.root, self.load, self.score = graph_path, root, load, score
        self.loaded: Any = None
        self.stamp, self.greps = None, None

    def graph(self):
        stamp = self.graph_path.stat().st_mtime_ns
        if stamp != self.stamp:
            self.loaded, self.stamp = self.load(str(self.graph_path)), stamp
        return self.loaded

    def call(self, name: str, args: dict) -> tuple:
        """(text, is_error) for one tool call."""
        if not str(args.get(REQUIRED.get(name, ""), "")).strip():
            return f"{name} needs `{REQUIRED.get(name)}`", True
        if name == "graph_continue":
            graph = self.graph()
            result = continue_flow(graph, args["task"], self.root, lambda t: self.score(graph, t))
            result["graph_commit"] = graph.graph.get("built_at_commit", "")
            self.greps = result["max_supplementary_greps"]
            return json.dumps(result, ensure_ascii=False, indent=1), False
        if name == "graph_read":
            return read(self.root, args["file"]), False
        if name == "graph_callers":
            return callers(self.graph(), args["symbol"]), False
        if name == "fallback_rg":
            if self.greps is None:
                return "call graph_continue first", True
            if self.greps <= 0:
                return (
                    "fallback_rg budget used up; read the recommended files, use "
                    "graph_callers, or call graph_continue again for a new subtask"
                ), True
            self.greps -= 1
            return rg(self.root, args["pattern"], str(args.get("glob", ""))), False
        return f"unknown tool {name}", True


def rg(root: Path, pattern: str, glob: str = "") -> str:
    """fallback_rg: ripgrep in the clone, at most 5 matches per file and OUTPUT_LINES in all."""
    command = [
        "rg",
        "-n",
        "--no-heading",
        "-m",
        "5",
        "-e",
        pattern,
        *(["-g", glob] if glob else []),
    ]
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


def build_server(flow: Flow):
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
        content = [types.TextContent(type="text", text=text)]
        return types.CallToolResult(content=content, isError=error)

    return Server(
        "bimetri-graph", version="1", on_list_tools=on_list_tools, on_call_tool=on_call_tool
    )


def main(graph_path: Path, root: Path) -> int:
    import anyio
    from graphify.serve import (  # pyright: ignore[reportMissingImports]
        _load_graph,
        _query_terms,
        _score_nodes,
    )
    from mcp.server.stdio import stdio_server  # pyright: ignore[reportMissingImports]

    flow = Flow(graph_path, root, _load_graph, scorer(_score_nodes, _query_terms))
    flow.graph()
    server = build_server(flow)

    async def run() -> None:
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    anyio.run(run)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]).resolve()))

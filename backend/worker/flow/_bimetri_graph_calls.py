# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): code graph use of one agent call, for the dashboard.

The executor exports ``BIMETRI_RUN_ID`` for the agent CLI. The graph MCP server on the worker
(scripts/bimetri/_graph_calls.py) logs each tool call to
``~<worker user>/.local/share/bimetri-graph/calls/<run id>.jsonl``, for Claude and Codex alike.
After the call ``collect`` reads and removes that file, and ``summarize`` turns it into the
``graph`` block of the invocation's metadata.

Saved tokens are an estimate: without the graph the agent would have read each file the graph
answers pointed at once, whole. So saved = (sum of those file sizes - characters the graph tools
returned, fallback_rg included) / 4, never below zero.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

RUN_ENV = "BIMETRI_RUN_ID"
CHARS_PER_TOKEN = 4
COLLECT_TIMEOUT_SEC = 15
_CALLS_DIR = ".local/share/bimetri-graph/calls"


def run_env(run_id: int) -> dict[str, str]:
    """Environment the agent CLI gets, so the graph server can tell the run."""
    return {RUN_ENV: str(int(run_id))}


def summarize(text: str) -> dict[str, Any] | None:
    """The graph block for one call's log lines; None when the agent made no graph call."""
    tools: dict[str, int] = {}
    files: dict[str, int] = {}
    returned = errors = over = 0
    for raw in text.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(line, dict) or not line.get("tool"):
            continue
        tool = str(line["tool"])
        tools[tool] = tools.get(tool, 0) + 1
        returned += int(line.get("returned") or 0)
        errors += 1 if line.get("error") else 0
        over += 1 if line.get("over") else 0
        for path, size in (line.get("files") or {}).items():
            files[path] = max(files.get(path, 0), int(size or 0))
    if not tools:
        return None
    full = sum(files.values())
    return {
        "calls": sum(tools.values()),
        "tools": tools,
        "errors": errors,
        "over_budget": over,
        "files": len(files),
        "returned_chars": returned,
        "full_chars": full,
        "saved_tokens": max(0, full - returned) // CHARS_PER_TOKEN,
    }


def collect_command(run_id: int) -> str:
    """Print and remove the run's log, whichever user's home it is in (root reaches all)."""
    name = f"{int(run_id)}.jsonl"
    paths = f"/home/*/{_CALLS_DIR}/{name} ~/{_CALLS_DIR}/{name}"
    return f'for f in {paths}; do [ -f "$f" ] && cat "$f" && rm -f "$f"; done; true'


async def collect(adapter: Any, run_id: int) -> dict[str, Any] | None:
    """Graph block of the agent call that just ended; None on no calls or any failure."""
    ssh = getattr(adapter, "_ssh", None)
    if ssh is None:
        return None
    try:
        out, _err, _rc = await ssh.run_command(collect_command(run_id), timeout=COLLECT_TIMEOUT_SEC)
        return summarize(out)
    except Exception:
        logger.warning("graph call log of run %s not collected", run_id, exc_info=True)
        return None

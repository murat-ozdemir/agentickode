"""bimetri patch (D2 phase 1): tool and token counts of one AgenticKode run, from the transcript
the Claude CLI keeps on the worker. AgenticKode stores neither tool calls nor the cache split.

Runs as the worker user (agent-graph-mcp.sh stats RUN sends it over SSH):
    stats RUN_ID    find the session whose prompt carries "`run_id` = RUN_ID" and summarise it
The run id comes from the project-memory block of the prompt, so projects without mem0 have no
match. Subagent transcripts of the session are counted too. Codex sessions are not read.
Bash commands are listed one per line (whitespace collapsed, long ones cut).
Stdlib only.
"""

import collections
import json
import os
import pwd
import re
import sys
from datetime import datetime
from pathlib import Path

GRAPH_PREFIX = "mcp__bimetri-graph__"
COMMAND_WIDTH = 160
RUN_MARK = re.compile(r"`run_id` = (\d+)\b")
USAGE_KEYS = (
    ("input", "input_tokens"),
    ("cache write", "cache_creation_input_tokens"),
    ("cache read", "cache_read_input_tokens"),
    ("output", "output_tokens"),
)


def home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def _records(path: Path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def _first_prompt(path: Path) -> str:
    for record in _records(path):
        if record.get("type") != "user":
            continue
        content = (record.get("message") or {}).get("content")
        if isinstance(content, list):
            content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
        return content if isinstance(content, str) else ""
    return ""


def find_sessions(projects: Path, run_id: int) -> list:
    """Main transcripts (not subagents) whose first prompt names this run."""
    found = []
    for path in sorted(projects.glob("*/*.jsonl")):
        marks = RUN_MARK.findall(_first_prompt(path))
        if str(run_id) in marks:
            found.append(path)
    return found


def summarise(paths: list) -> dict:
    tools, usage, reads = collections.Counter(), {}, set()
    times, commands = [], []
    for path in paths:
        for record in _records(path):
            stamp = record.get("timestamp")
            if stamp:
                times.append(datetime.fromisoformat(stamp.replace("Z", "+00:00")))
            message = record.get("message") or {}
            if record.get("type") != "assistant":
                continue
            # One API response is written as one line per content block, all with its usage.
            if message.get("id") and message.get("usage"):
                usage[message["id"]] = message["usage"]
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools[block.get("name", "?")] += 1
                    args = block.get("input") or {}
                    if block.get("name") == "Read":
                        reads.add(args.get("file_path"))
                    # Agents often search and read through the shell; Read alone misses that.
                    elif block.get("name") == "Bash" and args.get("command"):
                        commands.append(" ".join(str(args["command"]).split()))
    tokens = {label: sum(int(u.get(key) or 0) for u in usage.values()) for label, key in USAGE_KEYS}
    return {
        "duration": (max(times) - min(times)).total_seconds() if times else 0.0,
        "responses": len(usage),
        "tokens": tokens,
        "tools": dict(tools.most_common()),
        "graph_calls": sum(n for name, n in tools.items() if name.startswith(GRAPH_PREFIX)),
        "distinct_reads": len(reads - {None}),
        "commands": commands,
    }


def report(run_id: int, projects: Path) -> int:
    sessions = find_sessions(projects, run_id)
    if not sessions:
        print(f"run {run_id}: no Claude transcript on this worker")
        return 0
    for session in sessions:
        subagents = sorted((session.parent / session.stem).glob("subagents/*.jsonl"))
        stats = summarise([session, *subagents])
        print(f"run {run_id}: {session} (+{len(subagents)} subagent transcripts)")
        print(f"  duration {stats['duration']:.1f}s, API responses {stats['responses']}")
        print("  tokens: " + ", ".join(f"{k} {v}" for k, v in stats["tokens"].items()))
        tools = ", ".join(f"{k} {v}" for k, v in stats["tools"].items()) or "none"
        print(f"  tools: {tools}")
        print(
            f"  graph calls {stats['graph_calls']}, distinct files read {stats['distinct_reads']}"
        )
        for command in stats["commands"]:
            if len(command) > COMMAND_WIDTH:
                command = command[: COMMAND_WIDTH - 3] + "..."
            print(f"  $ {command}")
    return 0


def main(argv: list) -> int:
    if len(argv) == 2 and argv[0] == "stats" and argv[1].isdigit():
        return report(int(argv[1]), home() / ".claude" / "projects")
    print("usage: stats RUN_ID", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""bimetri patch (D2 phase 1): local code graph for the agent CLIs on a worker.

Runs as the worker user (agent-graph-mcp.sh sends it over SSH):
    install            stdin: own source, then the frozen locks (agent-graph-locks/<tool>.txt)
    update TOOL ROOT   TOOL: graphify | graperoot | all
    mode MODE          MODE: none | graphify | graperoot
    serve TOOL         update, then stdio MCP server; Claude/Codex start it in the run workspace
One venv per tool under ~/.local/share/bimetri-graph. Graph data goes to data/<tool>/<root slug>,
outside the clone, so `git status` and `clean -fd` never see it. Stdlib only, no network.
"""

import fcntl
import json
import os
import pwd
import re
import subprocess
import sys
import time
from pathlib import Path

NAME = "bimetri-graph"
TOOLS = ("graphify", "graperoot")
LOCK_MARK = "### lock: "  # install stdin: source, then "### lock: <tool>" + lock lines
# Same code path as graperoot's own graph_scan tool: incremental, writes the symbol index too.
GRAPEROOT_SCAN = """
import asyncio, json, sys
from graperoot.mcp_graph_server import build_server
async def main():
    res = await build_server(host="127.0.0.1", port=0).call_tool(
        "graph_scan", {"project_root": sys.argv[1]})
    out = res[1] if isinstance(res, tuple) else res
    print(json.dumps(out))
    sys.exit(0 if out.get("ok") else 1)
asyncio.run(main())
"""
_CODEX_TABLE = re.compile(r"^\[mcp_servers\.(?:\"bimetri-graph\"|bimetri-graph)[.\]]")


def home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def base_dir() -> Path:
    return home() / ".local" / "share" / NAME


def data_dir(tool: str, root: Path) -> Path:
    return base_dir() / "data" / tool / str(root).strip("/").replace("/", "__")


def tool_env(tool: str, root: Path) -> dict:
    env, data = dict(os.environ), str(data_dir(tool, root))
    if tool == "graphify":
        env.update(GRAPHIFY_OUT=data, GRAPHIFY_QUERY_LOG_DISABLE="1", GRAPHIFY_NO_TIPS="1")
    else:
        env.update(DG_DATA_DIR=data, DUAL_GRAPH_PROJECT_ROOT=str(root))
    return env


def update_command(tool: str, root: Path) -> list:
    venv = base_dir() / tool / "bin"
    if tool == "graphify":
        return [str(venv / "graphify"), "update", str(root)]
    return [str(venv / "python"), "-I", "-c", GRAPEROOT_SCAN, str(root)]


def server_command(tool: str, root: Path) -> list:
    python = str(base_dir() / tool / "bin" / "python")
    if tool == "graphify":
        return [python, "-m", "graphify.serve", str(data_dir(tool, root) / "graph.json")]
    return [python, "-m", "graperoot.mcp_graph_server", "--stdio"]


def update(tool: str, root: Path, out=None) -> int:
    data = data_dir(tool, root)
    data.mkdir(parents=True, exist_ok=True)
    with open(data.parent / (data.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        started = time.monotonic()
        # stdout=2: tool output goes to stderr, stdout carries only the summary line.
        done = subprocess.run(
            update_command(tool, root), env=tool_env(tool, root), cwd=root, stdout=2
        )
        elapsed = time.monotonic() - started
    print(f"{tool}: update rc={done.returncode} in {elapsed:.1f}s", file=out or sys.stdout)
    return done.returncode


def split_bundle(text: str) -> tuple:
    parts, name = {"": []}, ""
    for line in text.splitlines(keepends=True):
        if line.startswith(LOCK_MARK):
            name = line[len(LOCK_MARK) :].strip()
            parts[name] = []
        else:
            parts[name].append(line)
    return "".join(parts.pop("")), {k: "".join(v) for k, v in parts.items()}


def install(bundle: str) -> int:
    source, locks = split_bundle(bundle)
    missing = [tool for tool in TOOLS if not locks.get(tool, "").strip()]
    if missing:
        print(f"ERROR: no lock for {', '.join(missing)} on stdin", file=sys.stderr)
        return 1
    base = base_dir()
    base.mkdir(parents=True, exist_ok=True)
    (base / "agent_graph.py").write_text(source)
    for tool in TOOLS:
        venv = base / tool
        if not (venv / "bin" / "python").exists():
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, cwd=base)
        lock = base / f"{tool}.lock.txt"
        lock.write_text(locks[tool])
        pip = [str(venv / "bin" / "pip"), "install", "-q", "--disable-pip-version-check"]
        subprocess.run([*pip, "-r", str(lock)], check=True, stdout=2, cwd=base)
        pinned = [line for line in locks[tool].splitlines() if line.startswith((*TOOLS, "mcp="))]
        print(f"{tool}: installed {' '.join(pinned)}")
    return 0


def _write_private(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(str(tmp), 0o600)
    os.replace(str(tmp), str(path))


def update_codex(path: Path, entry: "list | None") -> None:
    kept, skipping = [], False
    for line in path.read_text().splitlines() if path.exists() else []:
        if line.startswith("["):
            skipping = bool(_CODEX_TABLE.match(line))
        if not skipping:
            kept.append(line)
    if entry:
        kept += ["", f"[mcp_servers.{NAME}]", f"command = {json.dumps(entry[0])}"]
        kept += [f"args = {json.dumps(entry[1:])}", "startup_timeout_sec = 60"]
    text = "\n".join(kept).strip()
    _write_private(path, text + "\n" if text else "")


def update_claude(path: Path, entry: "list | None") -> None:
    data = json.loads(path.read_text()) if path.exists() else {}
    servers = data.setdefault("mcpServers", {})
    servers.pop(NAME, None)
    if entry:
        servers[NAME] = {"type": "stdio", "command": entry[0], "args": entry[1:], "env": {}}
    _write_private(path, json.dumps(data, indent=2) + "\n")


def set_mode(mode: str) -> int:
    entry = [sys.executable, str(base_dir() / "agent_graph.py"), "serve", mode]
    entry = entry if mode in TOOLS else None
    if (home() / ".codex").is_dir():
        update_codex(home() / ".codex" / "config.toml", entry)
        print(f"codex:  {mode}")
    else:
        print("codex:  skipped (~/.codex missing, log in first)")
    update_claude(home() / ".claude.json", entry)
    print(f"claude: {mode}")
    return 0


def serve(tool: str) -> int:
    found = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if found.returncode != 0:
        print(f"{NAME}: cwd {os.getcwd()} is not inside a git clone", file=sys.stderr)
        return 1
    root = Path(found.stdout.strip())
    graph = data_dir(tool, root) / ("graph.json" if tool == "graphify" else "info_graph.json")
    # Incremental update first: the run's reset may have changed files since the last build.
    # stdout is the MCP channel from here on, so the update reports on stderr.
    if update(tool, root, out=sys.stderr) != 0 and not graph.exists():
        return 1
    command = server_command(tool, root)
    os.execve(command[0], command, tool_env(tool, root))


def main(argv: list) -> int:
    os.environ["HOME"] = str(home())  # runuser may keep root's HOME; pip and the tools use it
    command, args = (argv[0], argv[1:]) if argv else ("", [])
    if command == "install" and not args:
        return install(sys.stdin.read())
    if command == "update" and len(args) == 2 and args[0] in (*TOOLS, "all"):
        tools = TOOLS if args[0] == "all" else (args[0],)
        return max(update(tool, Path(args[1]).resolve()) for tool in tools)
    if command == "mode" and len(args) == 1 and args[0] in (*TOOLS, "none"):
        return set_mode(args[0])
    if command == "serve" and len(args) == 1 and args[0] in TOOLS:
        return serve(args[0])
    print("usage: install | update TOOL|all ROOT | mode none|TOOL | serve TOOL", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

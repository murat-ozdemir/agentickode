"""bimetri patch (D2 phase 1-2): local code graph for the agent CLIs on a worker.

Runs as the worker user (agent-graph-mcp.sh sends it over SSH, after _agent_graph_config.py):
    install            stdin: own source, then "### lock: graphify" + agent-graph-locks/graphify.txt
                       and "### file: graph_flow.py" + the flow server (_graph_read.py, _graph_flow*.py)
    update TOOL ROOT   TOOL: graphify | all
    mode MODE          MODE: none | graphify (agent CLI settings and gate, see the config file)
    gate pre|mark      Claude hook (stdin: hook event JSON), written by mode graphify
    serve TOOL         the graph_flow.py stdio MCP server on the graph on disk, at once; when the
                       clone moved since the last build, an update runs beside it in the
                       background. The agent CLIs start it in the run workspace
One venv per tool under ~/.local/share/bimetri-graph. Graph data goes to data/<tool>/<root slug>,
outside the clone, so `git status` and `clean -fd` never see it. Stdlib only, no network.
"""

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

from _agent_graph_config import NAME, TOOLS, base_dir, home, set_mode  # bundle: drop
from _agent_graph_gate import gate  # bundle: drop

PART_MARK = "### "  # install stdin: source, then "### lock: <tool>" / "### file: <name>" parts
FLOW = "graph_flow.py"
# A hung update would hold the repo's lock, and with it every later update, for good.
UPDATE_TIMEOUT_SEC = 1800


def data_dir(tool: str, root: Path) -> Path:
    return base_dir() / "data" / tool / str(root).strip("/").replace("/", "__")


def tool_env(tool: str, root: Path) -> dict:
    env, data = dict(os.environ), str(data_dir(tool, root))
    env.update(GRAPHIFY_OUT=data, GRAPHIFY_QUERY_LOG_DISABLE="1", GRAPHIFY_NO_TIPS="1")
    return env


def update_command(tool: str, root: Path) -> list:
    return [str(base_dir() / tool / "bin" / "graphify"), "update", str(root)]


def server_command(tool: str, root: Path) -> list:
    python, graph = base_dir() / tool / "bin" / "python", data_dir(tool, root) / "graph.json"
    return [str(python), "-I", str(base_dir() / FLOW), str(graph), str(root)]


def clean_head(root: Path) -> "str | None":
    """HEAD of a clean work tree; None when anything is changed or untracked."""
    git = ["git", "-C", str(root)]
    status = subprocess.run([*git, "status", "--porcelain"], capture_output=True, text=True)
    if status.returncode != 0 or status.stdout.strip():
        return None
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True)
    return head.stdout.strip() or None


def built_at(tool: str, root: Path) -> Path:
    data = data_dir(tool, root)
    return data.parent / (data.name + ".head")


def lock_path(tool: str, root: Path) -> Path:
    data = data_dir(tool, root)
    return data.parent / (data.name + ".lock")


def update(tool: str, root: Path, out=None) -> int:
    data_dir(tool, root).mkdir(parents=True, exist_ok=True)
    with open(lock_path(tool, root), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        started, head = time.monotonic(), clean_head(root)
        try:
            # stdout=2: tool output goes to stderr, stdout carries only the summary line.
            rc = subprocess.run(
                update_command(tool, root),
                env=tool_env(tool, root),
                cwd=root,
                stdout=2,
                timeout=UPDATE_TIMEOUT_SEC,
            ).returncode
        except subprocess.TimeoutExpired:
            rc = 124
        elapsed = time.monotonic() - started
        # serve skips the update while the clean tree is still at this commit.
        built_at(tool, root).write_text(head if rc == 0 and head else "")
    print(f"{tool}: update rc={rc} in {elapsed:.1f}s", file=out or sys.stdout)
    return rc


def update_in_background(tool: str, root: Path) -> None:
    """Start `update` in its own session, unless one already runs for this clone.

    The agent CLI waits seconds for the server, an update takes ~50 s on a large repo
    (platform-frontend, run #110), and the CLI ends serve when it gives up. So the update must
    not be serve's child in the foreground: it outlives serve and stamps the head itself.
    """
    data_dir(tool, root).mkdir(parents=True, exist_ok=True)
    with open(lock_path(tool, root), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"{tool}: an update is already running", file=sys.stderr)
            return
    log = data_dir(tool, root).parent / (data_dir(tool, root).name + ".log")
    with open(log, "w") as out:
        subprocess.Popen(
            [sys.executable, str(base_dir() / "agent_graph.py"), "update", tool, str(root)],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    print(f"{tool}: updating in the background, log {log}", file=sys.stderr)


def split_bundle(text: str) -> tuple:
    """(source, {tool: lock text}, {file name: text}) from the install stdin."""
    parts, name = {"": []}, ""
    for line in text.splitlines(keepends=True):
        kind, _, rest = line[len(PART_MARK) :].partition(": ")
        if line.startswith(PART_MARK) and kind in ("lock", "file") and rest.strip():
            name = f"{kind}: {rest.strip()}"
            parts[name] = []
        else:
            parts[name].append(line)
    texts = {k: "".join(v) for k, v in parts.items()}
    locks = {k[len("lock: ") :]: v for k, v in texts.items() if k.startswith("lock: ")}
    files = {k[len("file: ") :]: v for k, v in texts.items() if k.startswith("file: ")}
    return texts[""], locks, files


def install(bundle: str) -> int:
    source, locks, files = split_bundle(bundle)
    missing = [f"lock {tool}" for tool in TOOLS if not locks.get(tool, "").strip()]
    missing += [] if files.get(FLOW, "").strip() else [FLOW]
    if missing:
        print(f"ERROR: no {', '.join(missing)} on stdin", file=sys.stderr)
        return 1
    base = base_dir()
    base.mkdir(parents=True, exist_ok=True)
    (base / "agent_graph.py").write_text(source)
    (base / FLOW).write_text(files[FLOW])
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


def serve(tool: str) -> int:
    found = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if found.returncode != 0:
        print(f"{NAME}: cwd {os.getcwd()} is not inside a git clone", file=sys.stderr)
        return 1
    root = Path(found.stdout.strip())
    graph = data_dir(tool, root) / "graph.json"
    # The agent CLI waits only a few seconds for the server (alwaysLoad), so serve answers on
    # the graph on disk (reloaded when the update rewrites it) or, before the first build, with
    # a note. stdout is the MCP channel from here on, so serve reports on stderr.
    head, stamp = clean_head(root), built_at(tool, root)
    if graph.exists() and head and stamp.exists() and stamp.read_text() == head:
        print(f"{tool}: graph is at {head[:8]}, no update", file=sys.stderr)
    else:
        update_in_background(tool, root)
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
    if command == "gate" and args in (["pre"], ["mark"]):
        return gate(args[0], sys.stdin.read(), base_dir() / "gate")
    if command == "serve" and len(args) == 1 and args[0] in TOOLS:
        return serve(args[0])
    usage = "install | update TOOL|all ROOT | mode none|TOOL | serve TOOL | gate pre|mark"
    print(f"usage: {usage}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

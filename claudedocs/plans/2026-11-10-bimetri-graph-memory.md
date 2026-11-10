---
title: bimetri — local code graph for agents on workers (D2)
status: in-progress
date: 2026-11-10
related: [plans/2026-11-09-bimetri-memory-mcp.md, runbooks/bimetri-mem0-pgvector.md]
---

# bimetri — local code graph for agents on workers (D2)

## Goal

Give coding agents on the workers a local code graph (files, symbols, imports) over MCP. Agents
should find the relevant code with fewer reads. The graph is updated incrementally, never
rebuilt from scratch on each run.

## Findings that shape the design

- **No new worktree per run.** The default strategy is `shared_clone`
  (`_resolve_workspace_strategy`). Runs reuse `/workspaces/<org>/<repo>`. `workspace_setup` runs
  `fetch` → `checkout -f` → `reset --hard origin/<branch>` → `clean -fd`. The graph, kept
  outside the clone per clone path, survives between runs, and only the files changed since
  the last run need re-parsing.
- **Runs do not share a clone in practice.**
  - Webhook runs reach the queue without a worker. `get_workspace_server_id` picks one when
    the run starts (`select_workspace_for_run`): the server with the fewest active runs
    across all projects, then the one idle longest. Successive runs therefore rotate over
    .10/.11/.12.
  - The `(project, server)` check in `engine._dispatch_pending` and `max_concurrent_tasks`
    apply only to runs that already have a server.
  - dev-1 runs `max_concurrent_runs = 2`, and platform-backend has 3 workers, so a run always
    finds a worker with no active run. The worktree strategy is not needed.
  - If `max_concurrent_runs` is raised above the worker count, two runs can share a clone.
- **A run cannot be pinned to one worker.** Phase 1 therefore installs the tools on all three
  workers.
- **Run lifecycle in the clone.**
  - `workspace_setup` syncs the clone to `origin/<default>`.
  - `init` runs `checkout -b <branch>`; fix and test runs instead check out the PR branch and
    `pull` it.
  - The agent commits. `finalization` commits leftovers, pushes the branch and opens the PR.
  - The next run's `workspace_setup` resets the clone, after the previous push.
  - Local branches stay in the clone.
- **Git hooks fire at the wrong moments.**
  - Hooks run only for local git commands in the clone:
    - `post-checkout`: checkout/switch, clone, worktree add;
    - `post-merge`: merge, or a pull that merges;
    - `post-commit`: commit;
    - `post-rewrite`: amend, rebase.
  - `fetch`, `reset` and `clean` run no hook. A merge on Gitea happens on the server, so the
    worker's hooks never see it.
  - In our flow, `post-checkout` fires on `checkout -f <default>`, before the `reset --hard`
    that brings the new commits, so the graph would reflect the old tree.
  - The hooks fire again on `checkout -b` and on every agent commit.
  - Hooks would also run as whichever user runs git (root during setup), leaving
    root-owned graph files.
  - The update is therefore an explicit step, run as the worker user, after the reset.
- **graperoot can avoid the network** if we skip its launcher:
  - The launcher (`dgc`/`dg`) self-updates from GitHub/R2 and sends telemetry.
  - The MCP server pings the license server only in HTTP mode (`main()` →
    `_ping_license_server()`). `--stdio` mode (`_main_stdio`) does not ping.
  - The compiled modules (`graph_builder*.so` and others) contain no outside URL.
  - `graph_scan` already re-scans incrementally (`existing_nodes`).
  - Java is supported.
  - Engine license: proprietary, with no license file in the wheel. Only the launcher is
    Apache-2.0.
  - graperoot.dev/pricing lists a Free tier: "$0 forever", no account, no telemetry.
  - The Terms of Service govern the paid Pro tier (license key, per-person machines). No
    page restricts the Free tier's commercial or company use.
  - Privacy page: source code and file names never leave the machine.
  - Decision: the license is not a blocker for the Free tier on the workers.
- **Graphify** (`graphifyy`):
  - License: Apache-2.0/MIT. Parser: tree-sitter (Java included), no LLM with `--code-only`.
  - No telemetry. Query log in `~/.cache/graphify-queries.log`, off with
    `GRAPHIFY_QUERY_LOG_DISABLE=1`.
  - `--update` re-extracts only changed files. Stdio MCP via `graphify-mcp`.

## Scope

In scope:
- One graph tool on the workers, chosen by the user (see Decision below). Pinned version,
  installed in a venv under the worker user, no launcher, no auto-update.
- Graph data outside the clone, under the worker user's
  `~/.local/share/bimetri-graph/data/<tool>/<root slug>`. Agents cannot commit it, `git status`
  and `clean -fd` never see it, and no `.git/info/exclude` line is needed. (Earlier draft: inside
  the clone. Changed because graperoot ignores `.gitignore` and would index Graphify's output.)
- Run-start update: after `reset --hard` in `workspace_setup`, an incremental update of the
  graph. A failure is logged as a warning and never fails the run.
- Merge refresh: the Gitea merge webhook (already used for `ozellik_gecmisi`) triggers the same
  incremental update in the background on each worker that holds a clone of the repo. The next
  run-start update then has little or nothing to do.
- Stdio MCP server registered for Claude (`~/.claude.json`) and Codex (`~/.codex/config.toml`).
  It uses a wrapper that resolves the project root from the run's cwd (`git rev-parse
  --show-toplevel`), so one entry serves every repo on the worker.
- Worker setup script modeled on `scripts/bimetri/agent-memory-mcp.sh` (install, pin, register,
  `--dry-run`).
- A short Turkish "Kod grafiği" section in the repo AGENTS templates: when to use the graph tools.
  mem0 stays the project memory, and graperoot's `graph_add_memory` is not used.

Out of scope:
- Graph on the operator's machine. graperoot with `dgc` stays as it is.
- `worktree` strategy projects (none today). If needed later, copy the base clone's graph into
  the new worktree.
- Docs/PDF extraction that needs an LLM.
- Showing the graph in the crew UI.

## Decision needed (user)

| | graperoot (stdio, no launcher) | Graphify |
|---|---|---|
| Familiarity | In use on the operator's machine | New |
| License | Engine proprietary; Free tier with no written restriction | Apache-2.0 / MIT |
| Transport | stdio, spawned per agent session; no fixed HTTP port | stdio |
| Code | Compiled `.so`, cannot be reviewed | Open source |
| Network | None in stdio mode (verified in 3.10.19). A future version may add some, so the version is pinned | None (README) |
| Incremental | `graph_scan` with `existing_nodes` | `--update` |
| Tools | `graph_continue`, `graph_retrieve`, `graph_read`, `graph_neighbors`, `graph_impact`… | Query, path, explain (fewer, simpler) |

Neither the license nor the network is a blocker for either tool. The choice comes down to how
useful each one is to the agents, so Phase 1 measures it. The rest of the plan is the same for
both.

## Phase 1 — measure before choosing (9 Nov decision)

No independent benchmark exists for either tool.

1. Install both tools on all three workers, each as its own stdio MCP server. Runs rotate over
   the workers, so a script switches all three to the same mode (`none`, `graphify` or
   `graperoot`) before each measured run.
2. Build the platform-backend graph on each worker and record the build times.
3. Run the same small issue three times, all with the same agent and the same base commit:
   - without a graph;
   - with Graphify;
   - with graperoot.
4. Compare the three runs:
   - input/output tokens and cost (AgenticKode cost tracking);
   - duration;
   - file reads;
   - result quality (same acceptance criteria).

Phase 2 (the rest of this plan) rolls out the winner to all workers. If no tool clearly wins,
the plan is closed as `abandoned`, with the numbers.

### Phase 1 setup (built, 10 Nov)

- `scripts/bimetri/agent-graph-mcp.sh install|update|mode none|graphify|graperoot HOST...`, run
  as root on dev-1 with AgenticKode's SSH key; `--dry-run` prints the SSH commands. It sends
  `_agent_graph_mcp.py` (stdlib only) to each worker and runs it as the worker user.
- One venv per tool under `~/.local/share/bimetri-graph`, installed from frozen locks
  (`scripts/bimetri/agent-graph-locks/<tool>.txt`): `graphifyy[mcp]==0.9.105` with mcp 2.3.0;
  `graperoot==3.10.19` with mcp 1.19.0 and pydantic 2.13.3. Unpinned, pip pulls pydantic 2.14,
  which breaks mcp 1.19 (`eval_type_backport` import error), so the locks are required.
- Update commands, both LLM-free and incremental:
  - Graphify: `graphify update <root>` with `GRAPHIFY_OUT=<data dir>` (manifest-based).
  - graperoot: its own `graph_scan` tool, called in process (`build_server().call_tool`), so the
    symbol index is written too. The `graph-builder` CLI skips the symbol index.
- `mode` registers one stdio server `bimetri-graph` for Claude and Codex:
  `python3 ~/.local/share/bimetri-graph/agent_graph.py serve <tool>`. `serve` finds the root
  with `git rev-parse --show-toplevel` from its cwd, runs the incremental update (output on
  stderr; stdout is the MCP channel), then `exec`s the server. A failed update still serves an
  existing graph. Updating at every session start keeps the graph on the run's checkout, even
  when the previous run left the clone on its feature branch.
- Measured locally on agentickode-bimetri (768 files): Graphify first build 12.8–18.4 s,
  graperoot 1.1–1.7 s; no-change update about 1 s for each. Platform-backend timings come from
  `install` on the workers.
- Graphify's PR tools (`list_prs`, `get_pr_impact`, `triage_prs`) call the `gh` CLI, which the
  workers do not have, so they fail. Graphify does not use the network otherwise.
- Measurement issue and procedure: `ajan-ekibi` docs folder, `d2-graf-olcum-issue.md`.

## Technical Approach

- `scripts/bimetri/agent-graph-mcp.sh <worker> [--dry-run]`:
  - over SSH, create `~/.local/share/bimetri-graph/venv` and install the pinned package;
  - write the wrapper `~/.local/bin/bimetri-graph-mcp`;
  - register a stdio MCP server named `bimetri-graph` for Claude and Codex.
- Wrapper (stdio): `agent_graph.py serve <tool>`, built in Phase 1 (see Phase 1 setup).
  - graperoot: `DG_DATA_DIR=<data dir> DUAL_GRAPH_PROJECT_ROOT=$root python -m
    graperoot.mcp_graph_server --stdio`.
- `backend/services/bimetri_graph.py` (new): `refresh_graph(ssh, workspace, worker_user)`
  - runs `agent_graph.py update <tool> <workspace>` as the worker user with a timeout;
  - returns duration and file counts for the run log.
- `workspace_setup`: call `refresh_graph` after the `existing` clone is synced, only when the
  project opts in (`workspace_config["code_graph"] = true`).
- Merge webhook: after `ozellik_gecmisi`, the backend fans out over SSH to every worker whose
  clone of the project exists. It needs no broker: the backend already knows the workers and
  has SSH access to them.
  - Skip a worker that has an active run of the project; that run's clone sits on a feature
    branch. The next run-start update covers the skipped worker.
  - Otherwise sync the idle clone to `origin/<default>` (same commands as `workspace_setup`),
    then update the graph.
  - Fire-and-forget: errors only log.
- Both paths hold `flock <clone>/.git/bimetri-graph.lock`, so a run that starts during a merge
  refresh waits for it instead of resetting files under it.
- Tests:
  - unit tests for the command building in `refresh_graph` (exclude, timeout, run-as user);
  - unit tests for the opt-in in `workspace_setup`, the merge scheduling and the script
    (`--dry-run` output).
- Docs: runbook section and the Turkish guide (`ajan-ekibi-rehberi`), devir notu.

## Success Criteria

- [ ] Phase 1 numbers (no graph / Graphify / graperoot) recorded in this doc
- [ ] User picks the tool
- [ ] Tool installed on .10/.11/.12 with a pinned version; `claude mcp list` / `codex mcp list`
  show `bimetri-graph`
- [ ] First build time on platform-backend measured; second run-start update finishes in
  seconds
- [ ] Graph dir not in `git status` of the clone; survives `clean -fd`
- [ ] Merge of a PR refreshes the graph on the workers (log line with changed-file count)
- [ ] With graperoot: no outbound connection from the MCP process during a run (checked with
  `ss -tp` on the worker)
- [ ] A real run log shows the agent calling a graph tool
- [ ] Unit tests; ruff and pyright clean

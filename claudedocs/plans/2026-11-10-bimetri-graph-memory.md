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

**Decision (10 Nov, user): Graphify.** Agent runs cost the same with either tool; the direct
quality test (Phase 1c) decided it: Graphify found every dependent file and caller, graperoot
none. Phase 2 rolls out Graphify only; graperoot-specific items below no longer apply.

**Decision (10 Nov, user): agents get the graph**, despite Phase 1b's +39% cost, through a
mandatory flow modelled on GrapeRoot's Dual-Graph policy (the user's iklim.co sessions: agents
call `graph_continue` on their own, 335 times in that log), rebuilt on Graphify's graph.
graperoot is removed from the code and the workers.

### Phase 2 flow (built, 10 Nov)

Phase 1 exposed Graphify's own MCP tools with a soft hint; every run used grep instead. Phase 2
replaces them with four tools of our own over Graphify's `graph.json`, a policy text, and a gate.

| Tool | Returns |
|---|---|
| `graph_continue(task)` | `recommended_files` (`path` or `path::Symbol`) with `why` (relation + use-site line), `confidence`, `max_supplementary_greps` / `max_supplementary_files`, `graph_commit` |
| `graph_read(file)` | the file (first 400 lines), or with `::Symbol` only that declaration's block (braces matched, strings/comments skipped) |
| `graph_callers(symbol)` | every `calls` / `references` / `implements` / `inherits` / `imports` edge into the symbol, `file:line` |
| `fallback_rg(pattern, glob)` | ripgrep in the clone; refused before `graph_continue` and once its grep budget is spent |

- `graph_continue` seeds on the names in the task (camelCase / `name(` / file paths, capitalised
  words only if in the graph), then adds their users; method callers come before class users.
  `confidence`: high if every name was found once, medium if some are missing or ambiguous, low
  if nothing matched and Graphify's own scorer was used. Caps (greps, files): high 1/2,
  medium 2/3, low 4/5.
- Policy text (Turkish) in `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` between markers:
  `graph_continue` first, read with `graph_read`, callers with `graph_callers` not grep, obey
  the caps (Grep/Glob/`rg`/`find` count), editing/building/testing/git are free.
- Gate (Claude only; Codex has no hooks): on by default with `mode graphify`. PreToolUse denies
  every tool but `graph_continue` and `ToolSearch` until a `graph_continue` Post(ToolUse|Failure)
  writes the session's marker.
- Files: `_graph_flow.py` (logic, no networkx) + `_graph_flow_server.py` (mcp 2.x stdio server,
  Graphify's loader and scorer), bundled into `graph_flow.py`; `serve` runs it with the Graphify
  venv's python `-I`. The graph is reloaded when `graph.json` changes.
- Worker check (agent-1, `ResourceStatusService.update()`): `confidence` high, 15 files with
  the 8 `update` call sites first; `graph_read …::update` returns the overloads without the
  Javadoc mention; `fallback_rg` refused before `graph_continue` and after its one grep; gate
  denies `Grep` / `graph_read` before `graph_continue`, allows after.
- The gate also enforces the grep budget (`_agent_graph_gate.py`): Grep, Glob, `fallback_rg` and
  shell lines that start with rg/grep/find (also behind `&&`, `;`, `$(`, `xargs`) draw on
  `max_supplementary_greps`; at zero they are denied. A filter after a pipe is free.

### Phase 2 trial (criteria fixed before the runs, 10 Nov)

Two runs of the Phase 1b task (rename to `updateByNetworkId`), sonnet-5-5 medium, base
`7a010367`, workers in `mode graphify` with the gate. The flow passes only if both runs meet all:

| Criterion | Pass |
|---|---|
| Result | 5/5 callers renamed, `ActionUtils` 4-arg overload untouched, CI gate green |
| Flow used | at least one `graph_callers` or `graph_read` call after `graph_continue` |
| Searches | grep-type calls within the cap; denials are counted, not a failure on their own |
| Cost | mean of the two ≤ $0.155 (graphless mean $0.129 + 20 % noise band) |

These criteria measure this flow's cost; they do not decide whether agents get the graph. The
user decided the graph stays (10 Nov, after this trial): they have used it for months and see the
benefit. A failed criterion means the flow gets cheaper, not that the graph goes.

Result (10 Nov): **correct, but over the cost criterion. Workers stay in `mode graphify` with the
gate; the findings below are the next work.**

| Run | Worker | Time | Cost | Cache write / read | Output | Calls |
|---|---|---|---|---|---|---|
| #95 (issue #78, PR #79) | agent-1 | 56.6 s | $0.3570 | 68.4k / 441.5k | 3.9k | continue 1, callers 3, read 8, fallback_rg 2, Bash grep 1; 1 search denied |

- Result: 5/5 callers renamed, `ActionUtils` untouched, test run #96 (codex) added 3 tests, CI
  gate green. Flow used: yes.
- Cost: 2.8× the graphless mean ($0.129), 2× the Phase 1b graph runs ($0.178). `graph_read` of
  a caller returns its whole enclosing method (120–250 lines) to show a one-line call site;
  cache write doubled (68k vs 35k).
- The cap hurt the answer: after the denial the agent wrote in the PR that it could not list
  every caller and relied on the compiler instead.
- Run 2 was not started: with #95 at $0.357 the mean is at least $0.178 even if run 2 were
  free, so the cost criterion fails whatever it does.
- Cleanup: PR #79 closed unmerged, branch deleted, #78 closed, clones back on `7a010367`.
- After the trial I wrongly switched the workers to `mode none` and marked this plan
  `abandoned`; the user reversed that the same day and the workers are back in `mode graphify`
  with the gate (`✔ Connected` on all three).

Next (from #95):

- [ ] `graph_read`/`graph_callers`: return the call lines with a few lines of context, not the
  whole enclosing method.
- [ ] Grep cap: soften it (warn, or allow searches that complete a caller list) so the agent does
  not give up on completeness.
- [ ] Deploy the merge refresh to dev-1 and watch it on a real merge.

### Merge refresh (built 10 Nov, approved before the trial)

`backend/services/bimetri_graph.py`: the Gitea merge webhook (`_bimetri_pr_merged`) calls
`schedule_refresh`; for each worker of the project with no pending or running run of it, a
background task runs over SSH, under `flock -n <clone>/.git/bimetri-graph.lock`: fetch,
`checkout -f`/`reset --hard origin/<default>`/`clean -fd`, `chown -R` to the worker user, then
`agent_graph.py update graphify <clone>` as that user. Workers without `agent_graph.py` and
projects that are not `existing` or use `local_path` are skipped. `workspace_setup` waits on the
same lock (`flock -w 600`) before it syncs the clone. Errors only log. Not yet seen on a real
merge.

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
  `_agent_graph_config.py` + `_agent_graph_mcp.py` (stdlib only, joined into one program) to
  each worker and runs it as the worker user. `--direct` takes SSH destinations that log in as
  the worker user themselves (e.g. `~/.ssh/config` aliases) instead of root plus `runuser`.
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
  when the previous run left the clone on its feature branch. A successful update of a clean
  tree stamps its HEAD (`<data dir>.head`); while the tree is clean at that commit, `serve`
  skips the update and starts at once (a no-change Graphify update still takes ~4 s).
- Startup time (10 Nov, agent-1): after a 3-file checkout `graphify update` took 51.7 s (no
  change: 3.9 s), past Claude's 30 s MCP startup limit, so the server never connected. `mode`
  now writes `MCP_TIMEOUT=120000` to the worker user's `~/.claude/settings.json` (`env`) and
  `startup_timeout_sec = 120` for Codex, and checks with `claude mcp list` inside `--repo` (from
  the home directory `serve` finds no clone and always fails). For the measured runs the clones
  are checked out at the base commit and updated beforehand, so the run-start update has nothing
  to do. The merge refresh above is the lasting fix.
- Measurement B (run 76, 10 Nov) was invalid: zero graph calls. The session init listed
  `bimetri-graph` as `pending` with no tools. Two Claude Code defaults
  (code.claude.com/docs/en/mcp): MCP tools are deferred behind tool search (the agent sees only
  names and must call `ToolSearch`), and startup does not wait for slow servers. Fix (`mode`):
  - `"alwaysLoad": true` on the Claude entry: tools in the first tool list, startup waits for
    the server up to `MCP_CONNECT_TIMEOUT_MS`, set to 15000 (default 5000) in `settings.json`;
  - the HEAD stamp above, so `serve` answers well within that wait;
  - a marked Turkish hint in `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` to use the graph
    before grep (mem0 got used because the prompt names it; nothing named the graph). `mode
    none` removes it.
  `stats` now lists `ToolSearch` queries next to the Bash commands.
- Measurement B rerun (run 78, 10 Nov, after the fix): the graph tools were in the tool list
  and the hint in the session, yet zero graph calls and zero `ToolSearch`; the agent worked
  with Bash only (grep, sed, a heredoc rewrite), as in A. Result as good as A (5/5, CI passed),
  $0.2414 vs A's $0.227. On this small task (callers easy to grep) the graph went unused;
  that is the finding, not something to force with an agent rule. graperoot counts git-ignored
  files too (1,224 vs 1,223 on agent-2, a Maven shade leftover), no effect on the measurement.
- Measurement C (run 80, 10 Nov, graperoot): server up in 0.7 s with 10 tools, hint in the
  session, again zero graph calls (Bash ×5); the Codex test agent made none either. Same correct
  result, $0.1946. Before C the clones still held earlier runs' branches (the answer), now
  deleted; clean them before every measured run.
- Phase 1 result: none of the four runs used a graph (A $0.227, B-invalid $0.169, B $0.241,
  C $0.195). Run-to-run spread (~±20%) is larger than any effect one run per mode could show,
  and this task gives no basis to pick Graphify or graperoot.
- Phase 1b, graph use forced (10 Nov): `mode TOOL gate` (`--gate` in the script) adds Claude
  hooks to the worker's `~/.claude/settings.json`. `PreToolUse` (`*`) runs `agent_graph.py gate
  pre`, which exits 2 (tool denied, Turkish message to the model) until the session has called
  a `mcp__bimetri-graph__*` tool; `PostToolUse`/`PostToolUseFailure` on those tools run `gate
  mark`, which writes `gate/<session_id>.ok`. `ToolSearch` stays open. Works under
  `--dangerously-skip-permissions` (smoke run: Bash denied, then a graph call, then Bash
  allowed). `mode none` removes the hooks. One trivial graph call opens the gate.
- Phase 1b task: rename the deprecated `ResourceStatusService.update(String[], String,
  DTOResourceStatus)` to `updateByNetworkId` and update its five callers in another module
  (the 4-argument overload, called from `ActionUtils`, stays). 3 modes × 2 runs, interleaved,
  10 min apart, same base commit `7a010367`, Claude Sonnet 5.5 medium, Codex test agent. Every
  PR was closed unmerged and its branch deleted.

  | Mode | Run | Duration | Cost | Cache write | Graph calls | Result |
  |---|---|---|---|---|---|---|
  | graphify + gate | #82 | 37.1 s | $0.1717 | 35.0k | 1 | 5/5, tests pass |
  | graperoot + gate | #84 | 37.1 s | $0.1778 | 34.9k | 1 | 5/5, tests pass |
  | none | #87 | 42.7 s | $0.1345 | 24.3k | 0 | 5/5, tests pass |
  | none | #89 | 31.1 s | $0.1227 | 21.5k | 0 | 5/5, tests pass |
  | graperoot + gate | #91 | 40.3 s | $0.1791 | 34.6k | 1 | 5/5, tests pass |
  | graphify + gate | #93 | 38.5 s | $0.1851 | 37.0k | 1 | 5/5, tests pass |

- Phase 1b result: mean cost graphify $0.178, graperoot $0.178, none $0.129 (graph modes +39%);
  mean duration 37.8 / 38.7 / 36.9 s. All six runs were correct. Every gated run made exactly
  one graph call to open the gate, then found the callers with grep as before. The extra cost
  is the graph tool schemas (`alwaysLoad`) in the prompt cache (~+12k cache write per run). On
  this kind of task the graph adds cost and no speed or quality. A run (#86) hit the claude.ai
  five-hour limit before its first turn and was repeated as #87.
- Cleanup note: the gitea MCP `delete_branch` answered "Branch Deleted" but left the branches
  (61, 63, 65, 67); they were deleted with `git push origin --delete` from a worker clone.
- Phase 1c, graph quality without an agent (10 Nov, agent-1, clone at `7a010367`): both servers
  were started the way the agent CLI starts them and asked the same questions over MCP; answers
  were checked against `git grep`.

  | Question (truth) | Graphify | graperoot |
  |---|---|---|
  | Files that depend on `ResourceStatusService` (12) | 12/12, 0 extra (`calls`/`imports`/`references` edges) | `graph_impact`: 0/12, lists only the file's own symbols |
  | Callers of `update(String[],String,DTOResourceStatus)` (5) | 5/5, plus `ActionUtils`: both `update` overloads are one node | `graph_neighbors`: 0/5, edges only go out of the file |
  | `graph_retrieve` / `query_graph` "which classes call ResourceStatusService update…" | 4 of 5 handlers in the first 45 nodes | 0/5 in the top 10 (keyword hits such as `InternalCallerIdProtocol`) |
  | Files that use the `Cache` interface (11) | 11/11 incl. both `implements`; found `SnmpSequenceUtilImpl`, which a `Cache<` grep missed | `graph_impact`: 0/11 |

  Cause on graperoot's side: its Java `imports` edges point at the package name
  (`com.bimetri….ResourceStatusService`), not at the file, so there are no reverse edges and
  `graph_impact` cannot see dependents; retrieval is keyword ranking. Graphify resolves imports
  and calls to nodes but merges same-name overloads. With the earlier numbers (agent cost and
  duration equal; update after a change 51 s vs 4 s; Graphify open source, graperoot a
  compiled proprietary engine) the result is: **Graphify** answers dependency questions
  correctly, graperoot does not on this Java code base; its only edge is update speed.
- `mode` also sets `disableClaudeAiConnectors: true` there: the workers log in with the
  operator's claude.ai subscription, whose connectors (mail, drive, calendar) would otherwise
  reach every agent. Machine-local; claude.ai itself is unchanged.
- Measured locally on agentickode-bimetri (768 files): Graphify first build 12.8–18.4 s,
  graperoot 1.1–1.7 s; no-change update about 1 s for each.
- platform-backend (1225 code files), first build on each of .10/.11/.12 (`install`, 10 Nov):
  Graphify 45.9–46.7 s (about 13,850 nodes, 37,470 edges); graperoot 6.5 s (about 1,223 files,
  8,860 symbols, 18,370 edges). The worker clones sat on different feature branches, hence the
  small count differences.
- Graphify's PR tools (`list_prs`, `get_pr_impact`, `triage_prs`) call the `gh` CLI, which the
  workers do not have, so they fail. Graphify does not use the network otherwise.
- `agent-graph-mcp.sh stats RUN_ID HOST...` fills the gap left by AgenticKode's cost tracking,
  which stores neither tool calls nor the cache split. It sends `_agent_run_stats.py` to each
  worker and, as the worker user, finds the Claude transcript
  (`~/.claude/projects/*/*.jsonl`) whose first prompt carries "`run_id` = N" (from the mem0
  block). Output: tool calls by name, graph calls apart, distinct files read, tokens (input,
  cache write, cache read, output, deduplicated per API response), duration, and every Bash
  command (run A searched and read only through the shell, which "distinct files read" does
  not see). Subagent transcripts are included; the Codex test run is not read.
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

- [x] Phase 1 numbers (no graph / Graphify / graperoot) recorded in this doc
- [x] User picks the tool (Graphify, 10 Nov)
- [x] Tool installed on .10/.11/.12 with a pinned version; `claude mcp list` shows
  `bimetri-graph` connected (10 Nov, `mode graphify`, gate on)
- [ ] First build time on platform-backend measured; second run-start update finishes in
  seconds
- [x] Graph dir not in `git status` of the clone (data outside the clone); survives `clean -fd`
- [ ] Merge of a PR refreshes the graph on the workers (built 10 Nov; not seen on a real merge)
- ~~With graperoot: no outbound connection from the MCP process during a run~~ (Graphify chosen)
- [x] A real run log shows the agent calling a graph tool (#95, 14 graph calls; cost failed)
- [x] Unit tests; ruff and pyright clean

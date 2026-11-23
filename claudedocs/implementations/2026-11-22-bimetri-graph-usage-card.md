---
title: "bimetri: Code graph usage and savings on the Dashboard"
status: implemented
date: 2026-11-22
related: [plans/2026-11-22-bimetri-graph-usage-card.md, plans/2026-11-10-bimetri-graph-memory.md]
---

# bimetri: Code graph usage and savings on the Dashboard

## What Was Built

A **Code graph** card on the Dashboard: runs that used the graph (of all runs, by agent), graph
calls, tokens saved with a dollar figure at the agent's input price, saved share, tokens saved per
day and a per-worker table (Runs, Calls, Saved, %, Total), for 7d / 30d / All. On Run detail each
agent call shows its graph calls per tool, fallback_rg calls past the budget, failed calls and the
saving. Savings are estimates.

## Key Files

| File | Purpose |
|------|---------|
| `scripts/bimetri/_graph_calls.py` | Run id lookup (own env, then ancestors' `/proc`), one JSON line per tool call |
| `scripts/bimetri/_graph_flow_server.py`, `agent-graph-mcp.sh` | Server calls the recorder after every tool call; bundle joins six files |
| `scripts/bimetri/_graph_reply.py`, `_graph_budget.py` | graph_read outline and 6k cap; per-call 60k budget and dedupe (Faz 1) |
| `scripts/bimetri/_graph_pack.py`, `backend/worker/flow/_bimetri_graph_pack.py` | Context pack: graph_continue + top entries' code in the prompt (Faz 2) |
| `backend/worker/flow/_bimetri_previous_run.py` | Previous attempt of the same task_id in the prompt (Faz 2) |
| `backend/worker/flow/_bimetri_graph_calls.py` | `run_env`, `collect` (cat + rm over SSH), `summarize` |
| `backend/worker/flow/executor.py` | Exports `BIMETRI_RUN_ID`, stores `metadata_.graph` on success and failure |
| `backend/services/bimetri_graph_usage.py`, `backend/repositories/graph_usage_repo.py`, `backend/api/bimetri_graph_usage.py` | Totals, per-day, per-worker; `GET /api/bimetri/analytics/graph?range=` |
| `backend/services/bimetri_run_tokens.py` | Graph calls' tokens against the pre-graph baseline (`run_tokens`) |
| `frontend/src/components/graph/*`, `frontend/src/api/graphUsage.ts` | Card, chart, worker table, formats |
| `frontend/src/components/shared/AgentQuotaStrip.tsx` | `aside` prop: side by side up to 2 accounts, stacked from 3 |
| `frontend/src/components/runs/InvocationGraphNote.tsx` | Graph line on the invocation row and drawer |

## How It Works

1. Executor → `BIMETRI_RUN_ID=<run>` in the agent CLI's environment.
2. Graph MCP server → `~/.local/share/bimetri-graph/calls/<run>.jsonl`: `ts, tool, returned,
   files {path: bytes}, error, over`.
3. After the agent call → `collect` reads and removes the file (`/home/*/…` and `~/…`),
   `summarize` → `{calls, tools, errors, over_budget, files, returned_chars, full_chars, saved_tokens}`.
4. API sums the blocks of the range's runs; saved share = 1 - returned / full characters.
5. `run_tokens` (2026-11-23): every agent call's tokens (in + out). Each graph call in the range
   is matched with the median of calls before the first graph call — same task (all
   `pr-comment-<PR>-*` runs are one task), agent family and phase; else same repo, agent and phase
   with at least 3 calls; else left out. The tile shows the signed change (− = fewer tokens),
   actual vs baseline, calls compared and turns per call (Claude `num_turns`; Codex tool items + 1).
6. Codex `shell_reads` (2026-11-23, Faz 1): commands that printed a source file (cat, sed -n,
   head, ...) per call, summed into `run_tokens`; the Saved share note shows them. Claude has a
   hook for these (`_agent_graph_gate.py`), Codex does not.
7. Faz 2 (2026-11-23): before the agent call the worker runs `agent_graph.py pack graphify ROOT`
   (task on stdin): graph_continue's answer plus up to 5 entries' code and callers, ≤ 15k
   characters, appended to the prompt. `pack/<run>.json` marks that code sent (dedupe note "in the
   prompt's context pack") and `gate/run-<run>` opens the Claude gate with the pack's grep budget.
   Implement runs also get the last agent call of the same task_id (files, error, end of its last
   message, ≤ 1.5k). Claude runs get `--max-turns` (implement 80, pr_review 40; agent settings
   `MAX_TURNS_<TYPE>`, 0 = off). Worker policy shortened to ~1.4k characters with a quiet build
   rule (`mvn -q`, `| tail -n 60`).

## Notes

- Workers need `scripts/bimetri/agent-graph-mcp.sh install <hosts>` to get the recorder; until
  then runs carry no graph block and the card shows zeros.
- A file pointed at by several calls counts once per agent call, at its largest size.
- Saved share covers file reads only; the quota goes on turns × context, which `run_tokens` shows.
  Calls before this change carry no turns, so turns per call fills in with new runs.
- Dollar figure uses the input rate in `MODEL_COST_RATES` (Codex runs on a subscription, so it is
  what the tokens would cost at API prices).
- A Claude run that reaches `--max-turns` ends without a result; the run outcome is a short
  "tur tavanına ulaştı" note and the work may be half done. Raise `MAX_TURNS_IMPLEMENT` if it
  shows up.
- A backend restart cuts a running run before `collect`; the run starts again and, before
  2026-11-23, its next call read both attempts' log as one (run #312: 205k sent against 171k of
  files). `discard_stale` now drops the leftover before the context pack and logs how many calls.
  `scripts/bimetri/pull-restart.sh` waits for running runs before restarting.

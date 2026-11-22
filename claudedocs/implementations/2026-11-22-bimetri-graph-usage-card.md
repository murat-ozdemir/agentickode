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
| `scripts/bimetri/_graph_flow_server.py`, `agent-graph-mcp.sh` | Server calls the recorder after every tool call; bundle now joins four files |
| `backend/worker/flow/_bimetri_graph_calls.py` | `run_env`, `collect` (cat + rm over SSH), `summarize` |
| `backend/worker/flow/executor.py` | Exports `BIMETRI_RUN_ID`, stores `metadata_.graph` on success and failure |
| `backend/services/bimetri_graph_usage.py`, `backend/repositories/graph_usage_repo.py`, `backend/api/bimetri_graph_usage.py` | Totals, per-day, per-worker; `GET /api/bimetri/analytics/graph?range=` |
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

## Notes

- Workers need `scripts/bimetri/agent-graph-mcp.sh install <hosts>` to get the recorder; until
  then runs carry no graph block and the card shows zeros.
- A file pointed at by several calls counts once per agent call, at its largest size.
- Dollar figure uses the input rate in `MODEL_COST_RATES` (Codex runs on a subscription, so it is
  what the tokens would cost at API prices).

---
title: "bimetri: Code graph usage and savings on the Dashboard"
status: implemented
date: 2026-11-22
related: [plans/2026-11-10-bimetri-graph-memory.md, implementations/2026-11-22-bimetri-graph-usage-card.md]
---

# bimetri: Code graph usage and savings on the Dashboard

## Goal

Show how much the workers' agents (Claude and Codex) use the code graph and roughly how many
tokens it saves them, per run, per worker and per day.

## Scope

- In: a log line per graph tool call on the worker, keyed by run; collecting it after each agent
  call into `agent_invocations.metadata_.graph`; `GET /api/bimetri/analytics/graph`; a **Code
  graph** card beside Subscription limits; a graph line under each agent call on Run detail.
- Out: exact token counts (the saving is an estimate); a graph on/off comparison run.

## Technical Approach

- The backend exports `BIMETRI_RUN_ID` for the agent CLI. The graph MCP server finds it in its own
  environment or in an ancestor's `/proc/PID/environ` (Codex passes MCP servers a short env list)
  and appends to `calls/<run>.jsonl` next to `graph_flow.py`.
- After the call the executor cats and removes that file over SSH and stores a summary.
- Saving = (size of every file the graph answers pointed at, once per call - characters the graph
  tools returned, fallback_rg included) / 4, never below zero.
- Layout: with up to 2 subscription accounts the card sits to the right of Subscription limits
  (account cards stacked); from 3 accounts the limits panel takes the full width and the card
  moves below it.

## Success Criteria

- [x] Every graph call of a run is logged, for Claude and Codex
- [x] The invocation keeps the summary, on failed calls too
- [x] Card: runs using graph, calls, tokens saved (≈ $), saved share, per-day chart, per-worker table
- [x] Run detail shows calls per tool, budget overruns and the saving per agent call
- [x] Backend and frontend tests, ruff, pyright, eslint, tsc clean

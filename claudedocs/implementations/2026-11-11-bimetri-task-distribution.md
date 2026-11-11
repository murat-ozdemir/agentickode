---
title: "bimetri: Task Distribution card"
status: implemented
date: 2026-11-11
related: [plans/2026-11-11-bimetri-task-distribution.md]
---

# bimetri: Task Distribution card

## What Was Built

A Dashboard card under the analytics charts: runs per day stacked by agent, server, model,
difficulty or type, and six lists (server with success rate, agent, model, difficulty, run type,
outcome) for 7 days, 30 days or all time. A list row filters the Runs list below; a chip clears it.

## Key Files

| File | Purpose |
|------|---------|
| `backend/services/bimetri_run_distribution.py` | `classify`, `build`, `matching_ids`, list order |
| `backend/repositories/run_distribution_repo.py` | Runs + server name + invocations (agent, model) |
| `backend/api/bimetri_distribution.py` | `GET /api/bimetri/analytics/distribution`, `matching_run_ids` |
| `backend/api/runs.py`, `repositories/task_run_repo.py` | `dist_*` params, `ids` filter |
| `frontend/src/components/distribution/` | Card, history bars, group list, colors |
| `frontend/src/pages/Dashboard.tsx` | Card + filter chip |
| `tests/unit/test_bimetri_run_distribution.py`, `tests/integration/test_bimetri_distribution_api.py`, `frontend/src/__tests__/TaskDistributionCard.test.tsx` | Tests |

## How It Works

The repository reads the runs of the range with their invocations; the pure classifier gives each
run one value per dimension (sentinels: `no server`, `no agent call`, `unknown`, `no label`).
`build` returns every dimension's per-day counts, so "Color by" switches without a refetch.
The Runs list filter recomputes the matching ids with the same classifier and passes them to
`TaskRunRepository.list_runs(ids=...)`.

## Notes

- Runs before model tracking (runs 5–24) had no model; it was written into their invocations'
  `metadata_` on dev-1 from the agent templates of that time (Codex `gpt-6-luna` for runs 5 and 10,
  else `gpt-6.1-terra`; Claude `claude-sonnet-5-5`)
- Server success rate = completed / (completed + failed); running and pending runs are left out
- The card loads on mount and range change; it does not follow live SSE updates

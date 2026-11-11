---
title: "bimetri: Task Distribution card"
status: implemented
date: 2026-11-11
related: [implementations/2026-11-11-bimetri-task-distribution.md]
---

# bimetri: Task Distribution card

## Goal

Show on the Dashboard how runs split by server, agent, model, difficulty, run type and outcome,
per day, and let a row filter the Runs list.

## Scope

**In scope**
- `GET /api/bimetri/analytics/distribution?range=7d|30d|all`: per-day counts for every dimension
  plus the totals per value (server with success rate)
- `/api/runs` filter `dist_dim` / `dist_value` / `dist_range` built on the same classifier
- Dashboard card: "Color by" (stacked bars) and range pills, six lists, top-5 models with "+N more"
- One-off: the model of the 20 early backfilled invocations (runs 5–24) written into `metadata_`

**Out of scope**
- New tables or migrations; per-call (rather than per-run) breakdowns

## Technical Approach

- One run counts once; its agent and model are those of its first invocation
- Difficulty from the `difficulty/*` label; type from `task_source_meta.review_mode`
  (comment → review, test → test, fix → fix, else task); days are UTC dates
- Pure classifier in `backend/services/bimetri_run_distribution.py`; the card and the filter both
  use it, so the counts and the filtered list agree

## Success Criteria

- [x] Card counts match the database for each range
- [x] Clicking a row filters the Runs list; the chip clears it
- [x] Color by and 7d/30d/All work without errors
- [x] Unit and integration tests; frontend component tests

---
title: "bimetri: request effort in Gitea's time tracker"
status: implemented
date: 2026-11-21
related: [implementations/2026-11-21-bimetri-time-tracking.md]
---

# bimetri: request effort in Gitea's time tracker

## Goal

Each request (issue + its PR) shows the total effort spent on it (agent + CI + human) in Gitea's time tracker.

## Scope

**In scope**
- Agent time per run, CI time per gate run, human time estimated at merge
- Written by agentickode itself (no cron); idempotent on webhook re-delivery

**Out of scope**
- Lead time from `created_at` (queue and idle days are not effort)
- Working-hours rules (people also work evenings); caps keep idle time out instead
- Reports: `issue-lead-time.py` stays a separate reporting tool

## Technical Approach

| Part | Source | When written | Owner |
|------|--------|--------------|-------|
| Agent | `TaskRun.started_at` → `completed_at` (failed/cancelled too, queue excluded) | run end (`execute_pipeline` finally) | bot |
| CI | latest `dev.yml` Actions run of the commit, `created_at` → final `ci-kapisi` status time | `/webhooks/gitea-ci` success/failure/error | bot |
| Human | each trace credited with time since the last handoff; 1 h cap (comment/review/push), 10 min cap (label/merge/close) | PR merge | bot (one entry: everyone's sum; split in the log) |

- Handoffs: bot timeline events, agent run ends, CI run ends, the person's own previous trace.
- A person with their own tracked time on the request (stopwatch/manual) is skipped.
- Target: the issue the PR closes, else the PR.

## Success Criteria

- [x] Run end writes agent time once (same user + `created` not written twice)
- [x] CI time written on green and red gates; red still opens the fix round
- [x] Human time estimated per person at merge, capped, own records win; written as one bot entry
- [x] Tests never reach a real Gitea or DB (conftest guard)

---
title: "bimetri: request effort in Gitea's time tracker"
status: implemented
date: 2026-11-21
related: [plans/2026-11-21-bimetri-time-tracking.md]
---

# bimetri: request effort in Gitea's time tracker

## What Was Built

agentickode writes the effort spent on a request to Gitea's time tracker (`POST /repos/{o}/{r}/issues/{n}/times`): agent run time, CI time and the estimated human time, all under the bot (the request's total is what matters, not who).

## Key Files

| File | Purpose |
|------|---------|
| `backend/worker/phases/_bimetri_time_tracking.py` | `add_time` (idempotent write, bot fallback), `record_run_time`, `record_ci_time`, Actions run span helpers |
| `backend/worker/phases/_bimetri_human_time.py` | `estimate_human_seconds` (pure), `record_human_time`, background entry `record_human_time_safely` |
| `backend/worker/pipeline.py` | `execute_pipeline` writes agent time in `finally` (completed, failed, cancelled) |
| `backend/api/webhooks_pr.py` | `/webhooks/gitea-ci`: final `ci-kapisi` → CI time; red → fix round as before |
| `backend/api/_pr_webhook_helpers.py` | `_bimetri_pr_merged` starts human time in the background |
| `tests/conftest.py` | `_no_real_time_tracking` autouse guard |

## How It Works

- Every entry's `created` is when that work ended; an entry with the same user and `created` is skipped, so re-delivered webhooks add nothing.
- CI end comes from the status's `updated_at`: `dev.yml` writes `ci-kapisi` in its last step, so the run is still in progress when the status arrives. Runner queue time counts (people wait for it).
- Human estimate: sort the issue and PR timelines; for each non-bot event, window = event time − latest of (handoffs before it, the person's previous event, issue creation); cap 1 h for `comment/review/code/pull_push/change_title/commit_ref`, 10 min otherwise; time-tracking events are ignored.
- Restarted runs reset `started_at`, so a retry is not counted twice.

## Notes

- Human time is one bot entry at merge (sum of everyone without their own record); the per-person split only goes to the log. Per-person entries would need `user_name` and repo admin on the bot's token; not needed now.
- The issue author's writing time is not counted (no start mark before creation).
- `_pr_webhook_helpers.py` was already over 200 lines; this change adds 12.

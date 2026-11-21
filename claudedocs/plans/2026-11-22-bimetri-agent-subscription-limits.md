---
title: "bimetri: agent subscription limits on the Dashboard"
status: implemented
date: 2026-11-22
related: [implementations/2026-11-22-bimetri-agent-subscription-limits.md]
---

# bimetri: agent subscription limits on the Dashboard

## Goal

Show the 5-hour and weekly usage of every Claude and Codex subscription the workers are signed in
with, one card per account, with the e-mail, the plan and the workers that use it.

## Scope

**In scope**
- A probe that runs on each worker as the run user and reads each agent's own account and limits
  (Claude: OAuth usage endpoint; Codex: `codex app-server` `account/rateLimits/read`)
- One stored row per `(provider, account)`; a shared account shows once with all its workers
- Scheduler every `AGENT_QUOTA_POLL_SECONDS` (600), `GET /api/bimetri/agent-quotas`, `POST /sync`
- Dashboard strip under the stats row: bars with pace tick and reset countdown, limit-hit state,
  read errors and unreachable workers
- Adapter registry so another agent (e.g. Antigravity via opencode) is one parser + one probe section

**Out of scope**
- Reading `rate_limit_event` from Claude's run stream (future work)
- Blocking or routing runs on a full limit; notifications
- API-key (pay-as-you-go) logins: shown with an error, no limits

## Technical Approach

- `worker_probe.py` (stdlib only) goes over stdin (`python3 -`, under `runuser -l` when the
  adapter would run as the worker user); it prints sanitized JSON, tokens never leave the worker
- Provider adapters turn each section into an `AccountReading`; `service.collect` reattaches each
  answering worker to the account it reports now and keeps the old mapping of unreachable servers
- A window whose reset time passed since the last reading is shown empty

## Success Criteria

- [x] Two workers on one Codex account → one card with both workers
- [x] A worker that switches account moves to the new card
- [x] Probe output carries no token (unit test)
- [x] Live read on worker-1 matches the agents' own numbers
- [x] Backend and frontend tests, ruff, pyright, eslint, tsc clean

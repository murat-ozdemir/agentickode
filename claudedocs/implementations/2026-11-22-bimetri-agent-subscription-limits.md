---
title: "bimetri: agent subscription limits on the Dashboard"
status: implemented
date: 2026-11-22
related: [plans/2026-11-22-bimetri-agent-subscription-limits.md]
---

# bimetri: agent subscription limits on the Dashboard

## What Was Built

A **Subscription limits** panel on the Dashboard, styled like Task Distribution and placed right above it; the account cards share the row equally (2 accounts in halves, 3 in thirds). Each Claude or Codex
subscription the workers use is one card: provider, plan, e-mail, a bar per window (5h, Weekly)
with a pace tick and the time to reset, and the workers (server + user) signed in with it. Red at
100 % ("Limit hit · <countdown>"), amber at 70 % or when usage runs more than 10 points ahead of
the time gone. A read error shows on the card with the time of the last good numbers; unreachable
workers show as "N issue(s)" in the header. Refresh probes all workers at once. UI text is English.

## Key Files

| File | Purpose |
|------|---------|
| `alembic/versions/048_bimetri_agent_quotas.py`, `backend/models/bimetri_agent_quota.py` | `bimetri_agent_quota_accounts`, unique `(provider, account_key)`, windows + workers JSON |
| `backend/services/bimetri_agent_quota/worker_probe.py` | Stdlib script run on the worker; prints `{claude, codex}` JSON without tokens |
| `backend/services/bimetri_agent_quota/probe.py` | Picks the run user like `AdapterFactory`, sends the script over stdin |
| `backend/services/bimetri_agent_quota/{claude,codex}_adapter.py`, `types.py`, `__init__.py` | Section → `AccountReading`; `ADAPTERS` registry |
| `backend/services/bimetri_agent_quota/service.py` | `collect` (account ↔ worker mapping), `summary` |
| `backend/worker/bimetri_agent_quota_scheduler.py`, `backend/api/bimetri_agent_quotas.py` | Poll loop; `GET /api/bimetri/agent-quotas`, `POST /sync` |
| `frontend/src/components/shared/AgentQuotaStrip.tsx`, `AgentQuotaCard.tsx`, `QuotaBar.tsx`, `quotaFormat.ts`, `hooks/useAgentQuotas.ts` | Strip, card, bar, colour/pace/countdown helpers, 60 s poll |

## How It Works

- **Claude**: `~/.claude/.credentials.json` access token → `GET api.anthropic.com/api/oauth/usage`
  (`anthropic-beta: oauth-2025-04-20`); `five_hour` / `seven_day` utilization and `resets_at`.
  Account from `~/.claude.json` `oauthAccount`, plan from `subscriptionType`. An expired token is
  not sent (the card shows the error until the agent's next run refreshes it).
- **Codex**: `codex app-server` over stdio, `account/read` + `account/rateLimits/read`; windows
  named by length (300 min = 5h, 10080 = Weekly). An API-key login gets an error, no limits.
- **Mapping**: a worker that answers is detached from every account and attached to the one it
  reports now; a server that cannot be reached keeps its old mapping and its error goes to the
  `bimetri_agent_quota_sync` app setting. A failed read never overwrites one another worker made
  of the same account in the same round. Accounts with no workers are hidden.
- **Staleness**: readings are up to one poll old; a window whose reset passed since then is shown
  at 0 %.

## Notes

- Each worker is probed every round, even when several share an account (one HTTP call each);
  the dedupe is in storage. Fine for a few workers; cache per account if that grows.
- `AGENT_QUOTA_POLL_SECONDS` (default 600, `0` turns polling off; Refresh still works).
- Adding an agent (e.g. Antigravity via opencode): a function in `worker_probe.py` returning its
  section, an adapter with `parse(section) -> AccountReading`, an entry in `ADAPTERS`, and a
  label in `PROVIDER_LABELS` (`quotaFormat.ts`).
- Future: read Claude's `rate_limit_event` from the run stream to update between polls.
- The Claude usage endpoint is not a documented public API; if it changes the card shows the
  error and the rest keeps working.

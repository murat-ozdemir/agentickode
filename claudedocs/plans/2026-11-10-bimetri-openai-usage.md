---
title: "bimetri: OpenAI API spend, credit balance and quota alert card"
status: implemented
date: 2026-11-10
related: [runbooks/bimetri-mem0-pgvector.md, plans/2026-11-09-bimetri-memory-mcp.md, implementations/2026-11-10-bimetri-openai-usage.md]
---

# bimetri: OpenAI API spend, credit balance and quota alert card

## Goal

A Dashboard card that shows the OpenAI API spend of mem0 and the memory proposals exactly as
platform.openai.com shows it, the credit left, and turns red (with one Slack message) when
OpenAI stops answering for lack of credit.

## Scope

**In scope**
- This month's spend (UTC calendar month) from the OpenAI Costs API, the same source as the
  platform's usage page; never computed from tokens × price
- Credits entered by hand ("Add credit": amount + date, default today); list with edit/delete;
  the first entry is the balance on the billing page at that time
- Remaining = credits − spend from the first entry's UTC day on
- "Son güncelleme" time; sync every 15 min and on demand; a sync error is shown, not hidden
- Quota alert: a 429 with `insufficient_quota` / `credit_balance_exhausted` from the proposal
  call or from mem0 → card red + one message to the enabled notification channels; cleared by
  a new credit entry or the next successful proposal call

**Out of scope**
- Claude / Codex subscription limits (the agents' own usage)
- Reading the credit balance from OpenAI (no API exists)
- Per-model or per-project breakdown (the platform already has it)

## Technical Approach

| Part | File |
|------|------|
| Tables `bimetri_openai_credits`, `bimetri_openai_costs` (daily, UTC) | `alembic/versions/047_bimetri_openai_usage.py`, `backend/models/bimetri_openai.py` |
| Costs API client + sync + summary | `backend/services/bimetri_openai_usage.py` |
| 15-min scheduler | `backend/worker/bimetri_openai_usage_scheduler.py` |
| Quota alert state (`app_settings`) + notification | `backend/services/bimetri_openai_alert.py` |
| `/api/bimetri/openai/{summary,sync,credits}` | `backend/api/bimetri_openai.py` |
| Balance card + spend chart (in the analytics rows) + credit popup | `frontend/src/components/shared/OpenAIBalanceCard.tsx`, `OpenAISpendChart.tsx`, `OpenAICreditsModal.tsx` |

- Costs API: `GET /v1/organization/costs`, Admin key (`OPENAI_ADMIN_KEY`, read-only
  Usage scope), `bucket_width=1d`, `limit=180`, `start_time` inclusive / `end_time` exclusive,
  cursor `next_page`. Each sync re-reads every day from min(month start, first credit day) up
  to now and overwrites the stored days, so late-arriving cost on earlier days is picked up.
- Amounts are summed as `Decimal` and rounded to cents only for display.
- Alert detection reads `error.code` (not `type`); `rate_limit_exceeded` is transient and
  ignored. mem0 wraps the OpenAI error in its own 500 body, so its text is searched for the
  two codes.

## Success Criteria

- [x] Month spend on the card equals platform.openai.com/usage for the same month, to the cent
- [x] Remaining equals the billing page's credit balance after the opening entry
- [x] Credit add / edit / delete from the popup; the date defaults to today
- [x] Sync runs every 15 min; last update and any sync error visible on the card
- [ ] Quota error → card red, one Slack message; a new credit entry clears it (unit-tested; not yet seen live, checked when a real quota error happens)
- [x] Unit + frontend tests; ruff, pyright clean
- [x] Deployed to dev-1 with the Admin key in `.env`

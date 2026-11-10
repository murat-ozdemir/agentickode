---
title: "bimetri: OpenAI API spend, credit balance and quota alert card"
status: implemented
date: 2026-11-10
related: [plans/2026-11-10-bimetri-openai-usage.md, runbooks/bimetri-mem0-pgvector.md]
---

# bimetri: OpenAI API spend, credit balance and quota alert card

## What Was Built

Two Dashboard widgets for the OpenAI API spend of mem0 and the memory proposals, placed in the
analytics rows: an **OpenAI Balance** metric card next to "Est. Total Cost" (credits entered by
hand minus Costs API spend, last update; sync error and alert reason in the tooltip, refresh and
"Add credit" icon buttons) and an **OpenAI Spend ($)** area chart next to "Cost by Agent ($)"
(this month per UTC day, month total in the title; an area so 31 days fit the narrow card).
"Add credit" opens a popup (amount + date, default today) with the latest 5 entries to edit or
delete and a "Show all (N)" toggle. Page width is `max-w-[1600px]` for the five-column rows. The UI text is English. When OpenAI refuses a call for
lack of credit the card turns red and the enabled notification channels get one message.

## Key Files

| File | Purpose |
|------|---------|
| `alembic/versions/047_bimetri_openai_usage.py` | `bimetri_openai_credits`, `bimetri_openai_costs` (one row per UTC day) |
| `backend/models/bimetri_openai.py`, `backend/repositories/openai_usage_repo.py` | Models + credit CRUD, daily cost upsert, spend since a day |
| `backend/services/bimetri_openai_usage.py` | Costs API client (pagination), `sync`, `summary` |
| `backend/worker/bimetri_openai_usage_scheduler.py` | Sync every `OPENAI_USAGE_POLL_SECONDS` (900) while `OPENAI_ADMIN_KEY` is set |
| `backend/services/bimetri_openai_alert.py` | Quota error detection, alert state in `app_settings`, one notification |
| `backend/api/bimetri_openai.py` | `GET /summary`, `POST /sync`, `GET/POST /credits`, `PATCH/DELETE /credits/{id}` under `/api/bimetri/openai` |
| `frontend/src/components/shared/OpenAIBalanceCard.tsx`, `OpenAISpendChart.tsx`, `OpenAICreditsModal.tsx`, `hooks/useOpenAIUsage.ts` | Balance card, spend chart, popup, shared 60 s poll (slots `extraMetric`/`extraChart` in `AnalyticsCharts`) |

## How It Works

- **Spend**: `GET /v1/organization/costs` with the Admin key, `bucket_width=1d`, `limit=180`,
  from min(UTC month start, first credit day) to now. Every sync re-reads that whole range and
  overwrites the stored days, so cost that OpenAI adds late to an earlier day is picked up. Values
  are summed as `Decimal`; rounding to cents (half up) happens only in the summary.
- **Remaining** = sum of credits − spend from the first credit's UTC day on. There is no balance
  API, so the first entry must be the credit balance shown on the billing page at that moment.
- **Sync state** (`app_settings` `bimetri.openai.sync`): `{at, error}`. A failed sync keeps the
  last good `at` and shows the error on the card.
- **Alert** (`bimetri.openai.alert`): the proposal call and the three mem0 calls pass their
  response to `check_quota`; a status ≥ 400 whose body contains `insufficient_quota` or
  `credit_balance_exhausted` sets the alert (mem0 wraps the OpenAI error in its own 500, so the
  body text is searched). Only the first error sends a message, to every enabled channel
  regardless of its event list. `rate_limit_exceeded` is ignored. A new credit entry or the next
  successful proposal call clears it.

## Notes

- On the opening day, spend made before the first entry (same UTC day) is counted against it, so
  the remaining can be a few cents low. Edit the opening amount if it differs from the billing page.
- The Costs API reports by UTC day; the platform's usage page shows the same buckets, so compare
  with the page set to the same month.
- The Admin key needs an Organization Owner to create it (read-only, Usage scope is enough). It
  covers the whole organization: if other projects in the org use the API their spend counts too.
- Agent search calls through `memory-mcp` go through mem0, so their embedding cost is included.

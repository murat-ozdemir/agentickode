# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: OpenAI API spend from the Costs API, the source of platform.openai.com/usage.

Spend is never computed from tokens x price: the daily buckets (UTC) the platform shows are
stored as reported and summed as Decimal, rounded to cents only for display. Each sync re-reads
every day from min(month start, first credit day) up to now, so cost that arrives late on an
earlier day is picked up. Off while OPENAI_ADMIN_KEY is empty.
"""

from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.repositories.app_setting_repo import AppSettingRepository
from backend.repositories.openai_usage_repo import OpenAIUsageRepository
from backend.services.bimetri_openai_alert import ALERT_KEY
from backend.services.http_client import get_http_client

COSTS_URL = "https://api.openai.com/v1/organization/costs"
SYNC_KEY = "bimetri.openai.sync"
MAX_PAGES = 20


def usage_enabled() -> bool:
    return bool(settings.openai_admin_key)


def cents(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _day_start(day: date) -> int:
    return int(datetime.combine(day, time(), UTC).timestamp())


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            error = exc.response.json()["error"]
            # The Costs API sends a plain string for a missing scope, an object otherwise.
            message = error if isinstance(error, str) else error["message"]
        except (ValueError, KeyError, TypeError):
            message = exc.response.text[:200]
        return f"OpenAI {exc.response.status_code}: {message}"
    return f"{type(exc).__name__}: {exc}"[:300]


async def fetch_daily_costs(start: date, end: datetime) -> dict[date, Decimal]:
    """Organization spend per UTC day in [start, end), every project and line item."""
    params: dict = {
        "start_time": _day_start(start),
        "end_time": int(end.timestamp()),
        "bucket_width": "1d",
        "limit": 180,
    }
    days: dict[date, Decimal] = {}
    for _ in range(MAX_PAGES):
        resp = await get_http_client().get(
            COSTS_URL,
            headers={"Authorization": f"Bearer {settings.openai_admin_key}"},
            params=params,
            timeout=30.0,
        )
        resp.raise_for_status()
        body = resp.json()
        for bucket in body.get("data", []):
            day = datetime.fromtimestamp(bucket["start_time"], UTC).date()
            amounts = (Decimal(str(r["amount"]["value"])) for r in bucket.get("results") or [])
            days[day] = days.get(day, Decimal(0)) + sum(amounts, Decimal(0))
        if not (body.get("has_more") and body.get("next_page")):
            break
        params["page"] = body["next_page"]
    return days


async def sync(session: AsyncSession, now: datetime | None = None) -> str | None:
    """Store the spend days the summary needs; returns the error text, None on success."""
    now = now or datetime.now(UTC)
    first = await OpenAIUsageRepository(session).first_credit_on()
    start = min(now.date().replace(day=1), first or now.date())
    app_settings = AppSettingRepository(session)
    previous = await app_settings.get(SYNC_KEY) or {}
    try:
        days = await fetch_daily_costs(start, now)
    except Exception as exc:
        error = _describe(exc)
        await app_settings.set(SYNC_KEY, {"at": previous.get("at"), "error": error})
        return error
    await OpenAIUsageRepository(session).store_days(days, now)
    await app_settings.set(SYNC_KEY, {"at": now.isoformat(), "error": None})
    return None


async def summary(session: AsyncSession, now: datetime | None = None) -> dict:
    """What the Dashboard card shows; money in USD rounded to cents."""
    now = now or datetime.now(UTC)
    repo = OpenAIUsageRepository(session)
    month_start = now.date().replace(day=1)
    month_days = await repo.days_since(month_start)
    credits = await repo.list_credits()
    first = min((c.credited_on for c in credits), default=None)
    total = sum((Decimal(str(c.amount_usd)) for c in credits), Decimal(0))
    spent = await repo.spend_since(first) if first else None
    app_settings = AppSettingRepository(session)
    state = await app_settings.get(SYNC_KEY) or {}
    alert = await app_settings.get(ALERT_KEY) or None
    return {
        "enabled": usage_enabled(),
        "month_start": month_start,
        "month_spend_usd": cents(sum((v for _, v in month_days), Decimal(0))),
        "month_days": [{"day": d, "cost_usd": cents(v)} for d, v in month_days],
        "credits_total_usd": cents(total),
        "first_credit_on": first,
        "spent_since_first_credit_usd": cents(spent) if spent is not None else None,
        "remaining_usd": cents(total - spent) if spent is not None else None,
        "last_sync_at": state.get("at"),
        "sync_error": state.get("error"),
        "alert": alert,
    }

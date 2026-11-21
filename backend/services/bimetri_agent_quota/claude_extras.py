# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Claude model-scoped limits and usage-credit spend from the usage endpoint.

Both are read defensively: the endpoint is undocumented, and a credit-enabled or model-limited
account had not been seen when this was written. Unknown shapes are skipped, never guessed.
"""

from __future__ import annotations

import re

from backend.services.bimetri_agent_quota.types import (
    FIVE_HOUR_MINUTES,
    WEEK_MINUTES,
    QuotaWindow,
    to_percent,
)

ACCOUNT_WIDE_KINDS = {"session", "weekly_all"}
GROUP_MINUTES = {"session": FIVE_HOUR_MINUTES, "weekly": WEEK_MINUTES}
MODEL_SLOTS = {"seven_day_opus": "Opus", "seven_day_sonnet": "Sonnet"}


def _name(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("display_name") or value.get("name") or value.get("model")
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip().replace("_", " ")
    return value[:1].upper() + value[1:]


def _window(name: str, minutes: int | None, used: object, resets_at: object) -> QuotaWindow:
    key = "scope_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    reset = resets_at if isinstance(resets_at, str) else None
    return QuotaWindow(key, name, minutes, to_percent(used), reset, scope=name)


def scoped_windows(usage: dict) -> list[QuotaWindow]:
    """Limits that apply to one model only (e.g. a weekly Fable or Opus cap)."""
    out: list[QuotaWindow] = []
    seen: set[str] = set()
    for item in usage.get("limits") or []:
        if not isinstance(item, dict) or item.get("kind") in ACCOUNT_WIDE_KINDS:
            continue
        kind = item.get("kind")
        fallback = re.sub(r"^(weekly|session)_", "", kind) if isinstance(kind, str) else None
        name = _name(item.get("scope")) or _name(fallback)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        minutes = GROUP_MINUTES.get(item.get("group"))  # type: ignore[arg-type]
        out.append(_window(name, minutes, item.get("percent"), item.get("resets_at")))
    for slot, name in MODEL_SLOTS.items():
        window = usage.get(slot)
        if isinstance(window, dict) and name.lower() not in seen:
            out.append(
                _window(name, WEEK_MINUTES, window.get("utilization"), window.get("resets_at"))
            )
    return out


def _money(value: object) -> float | None:
    """``{amount_minor, exponent}`` -> major units; bare numbers have no known unit."""
    if not isinstance(value, dict):
        return None
    amount, exponent = value.get("amount_minor"), value.get("exponent", 2)
    if isinstance(amount, int | float) and isinstance(exponent, int):
        return round(amount / 10**exponent, 2)
    return None


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def credits_of(usage: dict) -> dict | None:
    """Usage credits that cover work past the plan limits; None while they are off and unused."""
    spend, extra = _dict(usage.get("spend")), _dict(usage.get("extra_usage"))
    used = _money(spend.get("used"))
    places = extra.get("decimal_places")
    if (
        used is None
        and isinstance(extra.get("used_credits"), int | float)
        and isinstance(places, int)
    ):
        used = round(extra["used_credits"] / 10**places, 2)
    enabled = bool(spend.get("enabled") or extra.get("is_enabled"))
    if not enabled and not used:
        return None
    limit = _money(spend.get("limit")) or _money(spend.get("cap"))
    percent = spend.get("percent") if spend.get("enabled") else extra.get("utilization")
    if not isinstance(percent, int | float):
        percent = used / limit * 100 if used is not None and limit else None
    currency = _dict(spend.get("used")).get("currency") or extra.get("currency") or "USD"
    return {
        "enabled": enabled,
        "used": used,
        "limit": limit,
        "balance": _money(spend.get("balance")),
        "currency": currency,
        "used_percent": to_percent(percent) if percent is not None else None,
        "limit_reached": bool(extra.get("spend_limit_reached")),
    }

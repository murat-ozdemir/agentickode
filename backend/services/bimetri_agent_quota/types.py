# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: provider-neutral shapes of an account's usage limits."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Protocol

FIVE_HOUR_MINUTES = 300
WEEK_MINUTES = 10080


@dataclass
class QuotaWindow:
    """One rolling limit window, e.g. the 5-hour or the weekly one."""

    key: str  # "five_hour", "weekly" or a provider-specific key
    label: str
    minutes: int | None
    used_percent: float  # 0-100
    resets_at: str | None = None  # ISO 8601, UTC

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AccountReading:
    """What one worker user's agent CLI reports about its subscription account.

    ``account_key`` is None when the CLI does not expose a stable id; the collector then keys
    the account by worker. ``error`` with no windows means the account is known but its usage
    could not be read this time.
    """

    provider: str
    account_key: str | None
    email: str | None = None
    plan: str | None = None
    org_name: str | None = None
    windows: list[QuotaWindow] = field(default_factory=list)
    limit_reached: bool = False
    error: str | None = None


class QuotaAdapter(Protocol):
    """Turns one provider section of the worker probe output into an ``AccountReading``."""

    provider: str

    def parse(self, section: dict) -> AccountReading: ...


def window_for(minutes: int | None, used: float, resets_at: str | None) -> QuotaWindow:
    """Name a window by its length, not by the slot the provider put it in."""
    if minutes == FIVE_HOUR_MINUTES:
        return QuotaWindow("five_hour", "5h", minutes, used, resets_at)
    if minutes == WEEK_MINUTES:
        return QuotaWindow("weekly", "Weekly", minutes, used, resets_at)
    label = f"{minutes // 60}h" if minutes and minutes % 60 == 0 else f"{minutes}m"
    return QuotaWindow(f"window_{minutes}", label, minutes, used, resets_at)


def epoch_to_iso(value: object) -> str | None:
    if not isinstance(value, int | float) or value <= 0:
        return None
    return datetime.fromtimestamp(value, UTC).isoformat()


def to_percent(value: object) -> float:
    return round(float(value), 1) if isinstance(value, int | float) else 0.0

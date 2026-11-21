# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Claude subscription limits from the OAuth usage endpoint (via the probe)."""

from __future__ import annotations

from backend.services.bimetri_agent_quota.claude_extras import credits_of, scoped_windows
from backend.services.bimetri_agent_quota.types import (
    FIVE_HOUR_MINUTES,
    WEEK_MINUTES,
    AccountReading,
    account_limit_hit,
    to_percent,
    window_for,
)

# usage key -> window length; utilization is already a 0-100 percentage
_WINDOWS = (("five_hour", FIVE_HOUR_MINUTES), ("seven_day", WEEK_MINUTES))


class ClaudeQuotaAdapter:
    provider = "claude"

    def parse(self, section: dict) -> AccountReading:
        account = section.get("account") or {}
        reading = AccountReading(
            provider=self.provider,
            account_key=account.get("accountUuid") or account.get("emailAddress"),
            email=account.get("emailAddress"),
            plan=section.get("plan"),
            org_name=account.get("organizationName"),
            error=section.get("error"),
        )
        usage = section.get("usage") or {}
        for key, minutes in _WINDOWS:
            window = usage.get(key)
            if not isinstance(window, dict):
                continue
            used = to_percent(window.get("utilization"))
            reading.windows.append(window_for(minutes, used, window.get("resets_at")))
        if reading.windows:
            reading.windows += scoped_windows(usage)
            reading.credits = credits_of(usage)
        reading.limit_reached = account_limit_hit(reading.windows)
        return reading

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Codex (ChatGPT plan) limits from ``codex app-server`` (via the probe)."""

from __future__ import annotations

from backend.services.bimetri_agent_quota.types import (
    AccountReading,
    epoch_to_iso,
    to_percent,
    window_for,
)


class CodexQuotaAdapter:
    provider = "codex"

    def parse(self, section: dict) -> AccountReading:
        account = section.get("account") or {}
        limits = section.get("limits") or {}
        reading = AccountReading(
            provider=self.provider,
            account_key=section.get("account_id") or account.get("email"),
            email=account.get("email"),
            plan=account.get("planType") or limits.get("planType"),
            error=section.get("error"),
        )
        if account.get("type") not in (None, "chatgpt"):
            reading.error = reading.error or "signed in with an API key; no plan limits"
        for slot in ("primary", "secondary"):
            window = limits.get(slot)
            if not isinstance(window, dict):
                continue
            reading.windows.append(
                window_for(
                    window.get("windowDurationMins"),
                    to_percent(window.get("usedPercent")),
                    epoch_to_iso(window.get("resetsAt")),
                )
            )
        reading.windows.sort(key=lambda w: w.minutes or 0)
        reading.limit_reached = bool(limits.get("rateLimitReachedType")) or any(
            w.used_percent >= 100 for w in reading.windows
        )
        return reading

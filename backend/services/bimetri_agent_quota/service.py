# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: probes every workspace server and keeps one row per subscription account.

Workers that share an account collapse into that account's ``workers`` list. A worker that
answers is moved to the account it reports now; a server that cannot be reached keeps its last
mapping, so its account does not vanish from the Dashboard during an outage.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AgentQuotaAccount
from backend.repositories.agent_quota_repo import AgentQuotaRepository
from backend.repositories.app_setting_repo import AppSettingRepository
from backend.repositories.workspace_server_repo import WorkspaceServerRepository
from backend.services.bimetri_agent_quota import ADAPTERS
from backend.services.bimetri_agent_quota.probe import ProbeResult, probe_server
from backend.services.bimetri_agent_quota.types import (
    AccountReading,
    QuotaWindow,
    account_limit_hit,
)

SYNC_KEY = "bimetri_agent_quota_sync"
_lock = asyncio.Lock()


def _same_worker(a: dict, b: dict) -> bool:
    return a.get("server_id") == b["server_id"] and a.get("user") == b["user"]


def _apply(account: AgentQuotaAccount, reading: AccountReading, fresh: bool, now: datetime) -> bool:
    """Copy a reading onto the row; returns True when it carried usage numbers."""
    account.email = reading.email or account.email
    account.plan = reading.plan or account.plan
    account.org_name = reading.org_name or account.org_name
    account.checked_at = now
    if reading.windows:
        account.windows = [w.to_dict() for w in reading.windows]
        account.credits = reading.credits
        account.limit_reached = reading.limit_reached
        account.observed_at = now
        account.error = None
        return True
    if not fresh:  # another worker of this account already read it this round
        account.error = reading.error or "no usage data"
    return False


async def collect(session: AsyncSession, now: datetime | None = None) -> None:
    """Probe all servers at once and store what they report."""
    async with _lock:
        now = now or datetime.now(UTC)
        servers = await WorkspaceServerRepository(session).list_all()
        probes: list[ProbeResult] = await asyncio.gather(*(probe_server(s) for s in servers))
        repo = AgentQuotaRepository(session)
        accounts = {(a.provider, a.account_key): a for a in await repo.list_all()}
        fresh: set[tuple[str, str]] = set()
        errors = []
        for server, probe in zip(servers, probes, strict=True):
            if probe.error:
                errors.append({"server_name": server.name, "error": probe.error})
                continue
            worker = {"server_id": server.id, "server_name": server.name, "user": probe.user}
            for account in accounts.values():  # it reports its current accounts below
                if any(_same_worker(w, worker) for w in account.workers or []):
                    account.workers = [w for w in account.workers if not _same_worker(w, worker)]
            for provider, section in probe.sections.items():
                adapter = ADAPTERS.get(provider)
                if adapter is None:
                    continue
                reading = adapter.parse(section)
                key = (provider, reading.account_key or f"worker:{server.id}:{probe.user}")
                account = accounts.get(key)
                if account is None:
                    account = AgentQuotaAccount(
                        provider=provider, account_key=key[1], windows=[], workers=[]
                    )
                    repo.add(account)
                    accounts[key] = account
                if _apply(account, reading, key in fresh, now):
                    fresh.add(key)
                account.workers = [*(account.workers or []), worker]
        await repo.commit()
        await AppSettingRepository(session).set(SYNC_KEY, {"at": now.isoformat(), "errors": errors})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _has_reset(window: dict, now: datetime) -> bool:
    try:
        return datetime.fromisoformat(window["resets_at"]) <= now
    except (KeyError, TypeError, ValueError):
        return False


def _as_window(w: dict) -> QuotaWindow:
    return QuotaWindow(
        w.get("key", ""),
        w.get("label", ""),
        w.get("minutes"),
        w.get("used_percent", 0),
        w.get("resets_at"),
        w.get("scope"),
    )


def current_windows(account: AgentQuotaAccount, now: datetime) -> tuple[list[dict], bool]:
    """Windows as of ``now``, and whether a limit is hit.

    Readings are up to one poll interval old; a window whose reset time has passed since then
    is shown empty instead of with its pre-reset usage.
    """
    windows = list(account.windows or [])
    if not any(_has_reset(w, now) for w in windows):
        return windows, bool(account.limit_reached)
    windows = [
        {**w, "used_percent": 0.0, "resets_at": None} if _has_reset(w, now) else w for w in windows
    ]
    return windows, account_limit_hit([_as_window(w) for w in windows])


async def summary(session: AsyncSession, now: datetime | None = None) -> dict:
    """Accounts that at least one worker uses, plus the last round's server errors."""
    now = now or datetime.now(UTC)
    state = await AppSettingRepository(session).get(SYNC_KEY) or {}
    accounts = [a for a in await AgentQuotaRepository(session).list_all() if a.workers]
    rows = []
    for a in accounts:
        windows, limit_reached = current_windows(a, now)
        rows.append(
            {
                "id": a.id,
                "provider": a.provider,
                "email": a.email,
                "plan": a.plan,
                "org_name": a.org_name,
                "windows": windows,
                "limit_reached": limit_reached,
                "credits": a.credits,
                "workers": a.workers,
                "error": a.error,
                "observed_at": _iso(a.observed_at),
                "checked_at": _iso(a.checked_at),
            }
        )
    return {
        "accounts": rows,
        "last_sync_at": state.get("at"),
        "errors": state.get("errors") or [],
    }

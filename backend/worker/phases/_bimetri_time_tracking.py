# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: write the effort spent on a request to Gitea's time tracker.

The total is agent + CI + human time:

- agent: each run's ``started_at`` → ``completed_at`` (failed and cancelled runs too,
  queue wait excluded), written under the bot when the run ends;
- CI: the ``dev.yml`` Actions run of a commit, written under the bot when the
  ``ci-kapisi`` status turns final (people wait at the screen for it, so it counts);
- human: estimated from people's traces at merge (``_bimetri_human_time``).

Everything is written under the bot: what matters is the request's total, not who.

An entry's ``created`` is the moment that piece of work ended. An entry with the same
``created`` already on the issue is not written again, so a re-delivered
webhook is harmless. Entries go to the issue the PR closes, else to the PR itself.
"""

import logging
from datetime import UTC, datetime

from backend.worker.phases._bimetri_ci import CI_WORKFLOW

logger = logging.getLogger("agentickode.phases.bimetri_time")

_PAGE = 50
_MAX_PAGES = 20


def parse_time(value) -> datetime | None:
    """ISO text or datetime → aware datetime (naive values are UTC); bad input → None."""
    if not value:
        return None
    if isinstance(value, datetime):
        d = value
    else:
        try:
            d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def get_json(gp, path: str, **params):
    r = await gp._client.get(
        f"{gp._base_url}/api/v1{path}", params=params or None, headers=gp._headers(), timeout=30.0
    )
    r.raise_for_status()
    return r.json()


async def list_all(gp, path: str, **params) -> list:
    """Every page of a Gitea list endpoint."""
    items: list = []
    for page in range(1, _MAX_PAGES + 1):
        batch = await get_json(gp, path, page=page, limit=_PAGE, **params)
        if not isinstance(batch, list):
            break
        items += batch
        if len(batch) < _PAGE:
            break
    return items


async def tracked_times(gp, rp: str, n: int) -> list[dict]:
    return await list_all(gp, f"/repos/{rp}/issues/{n}/times")


def _exists(times: list[dict], user: str, created: datetime) -> bool:
    return any(
        t.get("user_name") == user and parse_time(t.get("created")) == created for t in times
    )


async def add_time(gp, rp: str, n: int, seconds: float, created: datetime, bot: str) -> bool:
    """Write ``seconds`` under the bot on #n; True when an entry was written."""
    seconds = int(seconds)
    if seconds <= 0:
        return False
    created = created.astimezone(UTC).replace(microsecond=0)
    if _exists(await tracked_times(gp, rp, n), bot, created):
        return False
    r = await gp._client.post(
        f"{gp._base_url}/api/v1/repos/{rp}/issues/{n}/times",
        json={"time": seconds, "created": _iso(created)},
        headers=gp._headers(),
        timeout=30.0,
    )
    if r.status_code >= 300:
        logger.warning("%s#%s: time entry refused (%s)", rp, n, r.status_code)
        return False
    return True


def run_time_entry(run, now: datetime | None = None) -> tuple[str, int, float, datetime] | None:
    """(repo, number, seconds, end) for a finished Gitea run; None when nothing to write."""
    meta = run.task_source_meta or {}
    start = parse_time(run.started_at)
    n = meta.get("issue_number") or meta.get("pr_number")
    if run.git_provider != "gitea" or not start or not n:
        return None
    end = parse_time(run.completed_at) or now or datetime.now(UTC)
    rp = meta.get("repo_full_name") or f"{run.repo_owner}/{run.repo_name}"
    return rp, int(n), (end - start).total_seconds(), end


async def record_run_time(run, session) -> None:
    """Write the run's agent time; never raises."""
    try:
        entry = run_time_entry(run)
        if not entry:
            return
        from backend.services.git import get_git_provider
        from backend.services.http_client import get_http_client
        from backend.worker.phases._bimetri_oto import bot_login
        from backend.worker.phases._helpers import get_project_token

        gp = get_git_provider(
            "gitea", get_http_client(), access_token=await get_project_token(run, session)
        )
        rp, n, seconds, end = entry
        bot = await bot_login(gp)
        await add_time(gp, rp, n, seconds, end, bot)
    except Exception:
        logger.warning("Run #%s: agent time not written", getattr(run, "id", "?"), exc_info=True)


def ci_runs(data) -> list[dict]:
    """``dev.yml`` runs from an ``/actions/runs`` answer."""
    runs = (data or {}).get("workflow_runs") or []
    return [k for k in runs if CI_WORKFLOW in (k.get("path") or CI_WORKFLOW)]


def ci_span(run: dict, end: datetime | None = None) -> tuple[datetime, datetime] | None:
    """(start, end) of one Actions run; runner queue time counts as waiting too.

    ``end`` overrides the run's own end: dev.yml writes ``ci-kapisi`` in its last step,
    so the run is still in progress when that status arrives.
    """
    start = parse_time(run.get("created_at") or run.get("started_at") or run.get("run_started_at"))
    end = end or parse_time(run.get("completed_at") or run.get("updated_at"))
    return (start, end) if start and end and end > start else None


async def record_ci_time(gp, rp: str, sha: str, end: datetime | None = None) -> str:
    """Write the time of the latest ``dev.yml`` run of ``sha`` up to ``end`` (the final
    ``ci-kapisi`` status; default now); returns the outcome."""
    from backend.worker.phases._bimetri_ci_kirmizi import sha_pr
    from backend.worker.phases._bimetri_etiket import issue_no_bul
    from backend.worker.phases._bimetri_oto import bot_login

    runs = ci_runs(await get_json(gp, f"/repos/{rp}/actions/runs", head_sha=sha, limit=5))
    latest = max(runs, key=lambda k: k.get("id", 0)) if runs else None
    span = ci_span(latest, end or datetime.now(UTC)) if latest else None
    if not span:
        return "no CI run"
    pr = await sha_pr(gp, rp, sha)
    if not pr:
        return "no open PR"
    n = issue_no_bul(pr.get("body") or "") or int(pr["number"])
    bot = await bot_login(gp)
    start, end = span
    written = await add_time(gp, rp, n, (end - start).total_seconds(), end, bot)
    return f"#{n}: CI time {'written' if written else 'already there'}"

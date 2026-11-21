# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: estimate people's time on a request at merge, from their traces.

Gitea keeps no record of when someone started reading a PR, only when they acted. So a
person's action (a trace) is credited with the time since the last handoff: the latest
bot event, agent run end, CI run end or the person's own previous trace. That window is
capped: 1 h for a trace with content (comment, review, push), 10 min for a bare one
(label, merge, close). The caps keep idle nights and weekends out without any clock rule.
A person who already has tracked time on the request (stopwatch or manual entry) is
skipped: their own record beats the estimate. The others' total is one bot entry.
"""

import logging
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import or_, select

from backend.models import TaskRun
from backend.worker.phases._bimetri_time_tracking import (
    add_time,
    ci_runs,
    ci_span,
    get_json,
    list_all,
    parse_time,
    tracked_times,
)

logger = logging.getLogger("agentickode.phases.bimetri_human_time")

CONTENT_TYPES = {"comment", "review", "code", "pull_push", "change_title", "commit_ref"}
CONTENT_CAP = 3600
LIGHT_CAP = 600
# time tracking events are the person's own record, not a trace
_SKIP_TYPES = {
    "start_tracking",
    "stop_tracking",
    "cancel_tracking",
    "add_time_manual",
    "delete_time_manual",
}


def estimate_human_seconds(
    events: list[tuple[datetime, str, str]], handoffs: list[datetime], anchor: datetime | None
) -> dict[str, int]:
    """Seconds per person from human ``(time, login, type)`` events and handoff times."""
    marks = sorted(handoffs + ([anchor] if anchor else []))
    last_own: dict[str, datetime] = {}
    totals: dict[str, float] = defaultdict(float)
    for t, user, kind in sorted(events):
        starts = [m for m in marks if m < t]
        if user in last_own:
            starts.append(last_own[user])
        last_own[user] = t
        if not starts:
            continue
        cap = CONTENT_CAP if kind in CONTENT_TYPES else LIGHT_CAP
        totals[user] += min((t - max(starts)).total_seconds(), cap)
    return {u: int(s) for u, s in totals.items() if s >= 1}


async def run_ends(db, project_id: str, issue_no: int | None, pr_no: int | None) -> list[datetime]:
    """End times of the request's agent runs (issue run, AI review, test and fix runs)."""
    conds = []
    if issue_no:
        conds.append(TaskRun.task_id == str(issue_no))
    if pr_no:
        conds += [
            TaskRun.task_id.in_((f"pr-{pr_no}", f"pr-test-{pr_no}")),
            TaskRun.task_id.like(f"pr-comment-{pr_no}-%"),
        ]
    if not conds:
        return []
    q = select(TaskRun.completed_at).where(TaskRun.project_id == project_id, or_(*conds))
    rows = (await db.execute(q)).scalars().all()
    return [d for d in (parse_time(r) for r in rows) if d]


async def ci_ends(gp, rp: str, branch: str) -> list[datetime]:
    if not branch:
        return []
    data = await get_json(gp, f"/repos/{rp}/actions/runs", branch=branch, limit=50)
    spans = (ci_span(k) for k in ci_runs(data) if k.get("status") in (None, "completed"))
    return [s[1] for s in spans if s]


async def _traces(gp, rp: str, numbers: list[int], bot: str):
    """(human events, bot event times, earliest creation time) of the issue and PR."""
    events, bot_times, created = [], [], []
    for n in numbers:
        item = await get_json(gp, f"/repos/{rp}/issues/{n}")
        if d := parse_time(item.get("created_at")):
            created.append(d)
        for e in await list_all(gp, f"/repos/{rp}/issues/{n}/timeline"):
            t = parse_time(e.get("created_at"))
            user = (e.get("user") or {}).get("login") or ""
            kind = e.get("type") or ""
            if not t or not user or kind in _SKIP_TYPES:
                continue
            if user == bot:
                bot_times.append(t)
            else:
                events.append((t, user, kind))
    return events, bot_times, min(created, default=None)


async def record_human_time(
    gp, db, project_id: str, rp: str, issue_no: int | None, pr: dict
) -> dict[str, int]:
    """Write the estimated human total under the bot; returns the per-person breakdown."""
    from backend.worker.phases._bimetri_oto import bot_login

    pr_no = int(pr.get("number") or 0) or None
    numbers = [n for n in (issue_no, pr_no) if n]
    if not numbers:
        return {}
    target = numbers[0]
    bot = await bot_login(gp)
    events, bot_times, anchor = await _traces(gp, rp, numbers, bot)
    handoffs = bot_times + await run_ends(db, project_id, issue_no, pr_no)
    handoffs += await ci_ends(gp, rp, (pr.get("head") or {}).get("ref") or "")
    has_time = {t.get("user_name") for n in numbers for t in await tracked_times(gp, rp, n)}
    estimate = estimate_human_seconds(events, handoffs, anchor)
    counted = {u: s for u, s in estimate.items() if u not in has_time}
    end = parse_time(pr.get("merged_at")) or datetime.now(UTC)
    if not await add_time(gp, rp, target, sum(counted.values()), end, bot):
        return {}
    return counted


async def record_human_time_safely(project, rp: str, issue_no: int | None, pr: dict) -> None:
    """Background entry point for the merge webhook: own session, never raises."""
    from types import SimpleNamespace

    from backend.database import async_session
    from backend.services.git import get_git_provider
    from backend.services.http_client import get_http_client
    from backend.worker.phases._helpers import get_project_token

    try:
        async with async_session() as db:
            token = await get_project_token(
                SimpleNamespace(
                    git_provider="gitea",
                    project_id=project.project_id,
                    workspace_server_id=getattr(project, "workspace_server_id", None),
                ),
                db,
            )
            gp = get_git_provider("gitea", get_http_client(), access_token=token)
            written = await record_human_time(gp, db, project.project_id, rp, issue_no, pr)
        logger.info("%s PR #%s human time: %s", rp, pr.get("number"), written or "none")
    except Exception:
        logger.warning("%s PR #%s: human time not written", rp, pr.get("number"), exc_info=True)

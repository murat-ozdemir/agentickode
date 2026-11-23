# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a note on the PR (or the issue, before there is a PR) when a run starts.

Says which run started, why, which agent runs it and, in an automatic fix round, which round
it is, so the user can follow the chain in Gitea without the dashboard. The note has no
``@agentickode`` mention (the comment webhook ignores it) and carries ``START_MARKER`` so the
PR history given to agents leaves it out.
"""

import logging
import re

from backend.config import settings

logger = logging.getLogger("agentickode.phases.bimetri_start_note")

START_MARKER = "<!-- agentickode-start -->"
_AUTO_REASON_RX = re.compile(r"@agentickode\s+(.+?)\s+Uygulama kodunu düzelt", re.S)


def auto_reason(comment_body: str) -> str | None:
    """The reason an automatic fix round gives in its ``@agentickode`` comment (OTO_YORUM)."""
    m = _AUTO_REASON_RX.search(comment_body or "")
    return m.group(1).strip() if m else None


def run_kind(meta: dict) -> str:
    mode = meta.get("review_mode")
    if mode == "test":
        return "Test"
    if mode == "fix":
        return "Düzeltme"
    return "İnceleme" if mode else "Görev"


def _reason(meta: dict) -> str | None:
    if meta.get("start_reason"):
        return meta["start_reason"]
    mode = meta.get("review_mode")
    if mode == "test":
        return "`ai-test` etiketi"
    return "`ai-review` etiketi" if mode and mode != "fix" else None


def start_note(
    run, agent: str | None, model: str | None, effort: str | None, tour: str = ""
) -> str:
    meta = run.task_source_meta or {}
    url = f"{settings.app_base_url.rstrip('/')}/runs/{run.id}"
    lines = [f"▶️ **Koşu #{run.id} başladı: {run_kind(meta)}** · [{url}]({url})"]
    details = []
    reason = _reason(meta)
    if reason:
        details.append(f"Neden: {reason}")
    if agent:
        extra = ", ".join(x for x in (model, effort) if x)
        details.append(f"Ajan: {agent}" + (f" ({extra})" if extra else ""))
    if tour:
        details.append(f"Otomatik tur: {tour}")
    if details:
        lines.append(" · ".join(details))
    return "\n".join(lines) + "\n" + START_MARKER


def note_target(run) -> tuple[str, int] | None:
    """(repo, PR number, or the issue's before there is a PR); None outside Gitea."""
    meta = run.task_source_meta or {}
    n = meta.get("pr_number") or meta.get("issue_number")
    if run.git_provider != "gitea" or not n:
        return None
    return meta.get("repo_full_name") or f"{run.repo_owner}/{run.repo_name}", int(n)


async def announce_start(
    run, session, agent: str | None, model: str | None, effort: str | None
) -> None:
    """Posts the start note; never raises (the run goes on without it)."""
    try:
        target = note_target(run)
        if not target:
            return
        from backend.services.git import get_git_provider
        from backend.services.http_client import get_http_client
        from backend.worker.phases._bimetri_oto import OTO_TUR_SINIRI, oto_tur_sayisi
        from backend.worker.phases._helpers import get_project_token

        gp = get_git_provider(
            "gitea", get_http_client(), access_token=await get_project_token(run, session)
        )
        rp, n = target
        tour = ""
        if (run.task_source_meta or {}).get("auto_round"):
            tour = f"{await oto_tur_sayisi(gp, rp, n)}/{OTO_TUR_SINIRI}"
        await gp.post_pr_comment(rp, n, start_note(run, agent, model, effort, tour))
    except Exception:
        logger.warning("Run #%s: start note not posted", getattr(run, "id", "?"), exc_info=True)

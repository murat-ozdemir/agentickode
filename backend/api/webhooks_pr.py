# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""Webhook + CI endpoints that launch AI code-review runs for pull requests.

A PR review is gated by the ``ai-review`` label (GitHub / Gitea ``pull_request``
events) and routed through the ``pr-review`` workflow template via
``TriggerMatcher`` — the same label-driven routing the issue webhooks use. CI
systems can trigger a review directly with ``POST /api/webhooks/pr-review``
(repo + pr_number). Review runs are single-pass (``max_retries=0``) and carry
``review_mode="comment"`` so finalization posts the review instead of pushing.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api._pr_webhook_helpers import (
    GITEA_PR_ACTIONS,
    GITHUB_PR_ACTIONS,
    build_pr_review_run,
    handle_pr_event,
    resolve_pr_review_flow_prompt_id,
)
from backend.api.webhooks import _get_repo
from backend.config import settings
from backend.database import get_db
from backend.repositories.project_config_repo import ProjectConfigRepository
from backend.services.webhook_security import verify_shared_secret

logger = logging.getLogger("agentickode.webhooks")
router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/github-pr")
async def github_pr_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    repo: ProjectConfigRepository = Depends(_get_repo),
):
    """Receive GitHub pull_request events; review when labelled ``ai-review``."""
    return await handle_pr_event(
        request,
        db,
        repo,
        source="github",
        allowed_actions=GITHUB_PR_ACTIONS,
        secret=settings.github_webhook_secret,
        signature_header="X-Hub-Signature-256",
    )


@router.post("/webhooks/gitea-pr")
async def gitea_pr_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    repo: ProjectConfigRepository = Depends(_get_repo),
):
    """Receive Gitea pull_request events; review when labelled ``ai-review``."""
    return await handle_pr_event(
        request,
        db,
        repo,
        source="gitea",
        allowed_actions=GITEA_PR_ACTIONS,
        secret=settings.gitea_webhook_secret,
        signature_header="X-Gitea-Signature",
    )


class PrReviewTriggerRequest(BaseModel):
    """CI-facing payload to launch a review for an existing PR."""

    repo: str  # "owner/name"
    pr_number: int = Field(gt=0)
    provider: str = "github"
    pr_head_branch: str = ""
    pr_title: str = ""
    pr_body: str = ""
    labels: list[str] = []


@router.post("/webhooks/pr-review")
async def trigger_pr_review(
    payload: PrReviewTriggerRequest,
    db: AsyncSession = Depends(get_db),
    repo: ProjectConfigRepository = Depends(_get_repo),
    x_ci_token: str | None = Header(default=None),
):
    """Launch a PR-review run for ``repo``#``pr_number`` (CI/manual trigger).

    Unlike the webhook, this is an explicit request — it runs the ``pr_review``
    flow prompt and does not require the ``ai-review`` label. When
    ``CI_TRIGGER_SECRET`` is configured, callers must present a matching
    ``X-CI-Token`` header (constant-time compared); when it is unset the endpoint
    is open (protect it at the network layer).
    """
    if settings.ci_trigger_secret and not verify_shared_secret(
        settings.ci_trigger_secret, x_ci_token
    ):
        raise HTTPException(status_code=401, detail="invalid or missing X-CI-Token")

    owner, _, name = payload.repo.partition("/")
    project = await repo.get_by_git_repo(payload.provider, owner, name)
    if not project:
        raise HTTPException(status_code=404, detail=f"No project for {payload.repo}")

    run = build_pr_review_run(
        project,
        task_source=payload.provider,
        pr_number=payload.pr_number,
        pr_title=payload.pr_title or f"PR #{payload.pr_number}",
        pr_body=payload.pr_body,
        pr_head_branch=payload.pr_head_branch,
        pr_url="",
        repo_full_name=payload.repo,
        labels=payload.labels,
        flow_prompt_id=await resolve_pr_review_flow_prompt_id(db),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    logger.info("Created run #%d from CI pr-review trigger: %s", run.id, run.title)
    return {"status": "accepted", "run_id": run.id}


# bimetri yamasi: Gitea "status" webhook'u - kirmizi ci-kapisi botun PR'inda duzeltme turu acar
@router.post("/webhooks/gitea-ci")
async def gitea_ci_status_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    repo: ProjectConfigRepository = Depends(_get_repo),
):
    from backend.api._bimetri_push import proje_saglayici
    from backend.api._pr_webhook_helpers import read_verified_body
    from backend.worker.phases._bimetri_ci import CI_BAGLAM
    from backend.worker.phases._bimetri_ci_kirmizi import ci_kirmizi, sha_pr
    from backend.worker.phases._bimetri_notebook_record import record_ci
    from backend.worker.phases._bimetri_time_tracking import parse_time, record_ci_time

    body = await read_verified_body(request, settings.gitea_webhook_secret, "X-Gitea-Signature")
    state = body.get("state")
    if body.get("context") != CI_BAGLAM or state not in ("success", "failure", "error"):
        return {"status": "ignored", "reason": "not_final_gate"}
    full = (body.get("repository") or {}).get("full_name", "")
    owner, name = full.split("/", 1) if "/" in full else ("", full)
    project = await repo.get_by_git_repo("gitea", owner, name)
    if not project:
        return {"status": "ignored", "reason": "unknown_project"}
    gp = await proje_saglayici(project, db)
    sha = body.get("sha", "")
    try:  # bimetri patch: CI time counts as spent time (people wait for it)
        logger.info(
            "CI time %s %s: %s",
            full,
            sha[:8],
            await record_ci_time(gp, full, sha, parse_time(body.get("updated_at"))),
        )
    except Exception:
        logger.warning("CI time not written %s %s", full, sha[:8], exc_info=True)
    try:  # bimetri patch: the gate's result goes to the PR's chain notebook (item 7)
        pr = await sha_pr(gp, full, sha)
        if pr:
            await record_ci(db, project.project_id, pr["number"], sha, state == "success")
    except Exception:
        logger.warning("CI result not in notebook %s %s", full, sha[:8], exc_info=True)
    if state == "success":
        return {"status": "accepted", "reason": "ci_time"}
    sonuc = await ci_kirmizi(gp, full, sha, body.get("target_url") or "")
    logger.info("Kirmizi CI %s %s: %s", full, str(body.get("sha", ""))[:8], sonuc)
    return {"status": "accepted", "reason": sonuc}

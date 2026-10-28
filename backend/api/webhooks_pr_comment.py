# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""Webhook endpoint for PR review comments that @mention the agent."""

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.repositories.project_config_repo import ProjectConfigRepository
from backend.services.run_factory import create_task_run

logger = logging.getLogger("agentickode.webhooks.pr_comment")
router = APIRouter(tags=["webhooks"])

_MENTION_TRIGGERS = {"@agentickode", "@ai-agent", "@autofix"}


def _get_repo(db: AsyncSession = Depends(get_db)) -> ProjectConfigRepository:
    return ProjectConfigRepository(db)


# bimetri yamasi: Gitea PR yorumu (@agentickode ...) ayni PR dalinda duzeltme kosusu acar
@router.post("/webhooks/gitea-pr-comment")
async def gitea_pr_comment_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    repo: ProjectConfigRepository = Depends(_get_repo),
):
    import re
    from types import SimpleNamespace

    from sqlalchemy import select

    from backend.api._pr_webhook_helpers import read_verified_body
    from backend.config import settings
    from backend.models import TaskRun
    from backend.services.git import get_git_provider
    from backend.services.http_client import get_http_client
    from backend.worker.phases._helpers import get_project_token

    body = await read_verified_body(request, settings.gitea_webhook_secret, "X-Gitea-Signature")
    action = body.get("action", "")
    if action != "created":
        return {"status": "ignored", "reason": f"action_{action}"}
    issue = body.get("issue") or {}
    if not (body.get("is_pull") or issue.get("pull_request")):
        return {"status": "ignored", "reason": "not_pr"}
    comment = body.get("comment") or {}
    comment_body = comment.get("body") or ""
    if not any(t in comment_body.lower() for t in _MENTION_TRIGGERS):
        return {"status": "ignored", "reason": "no_mention"}

    full = body.get("repository", {}).get("full_name", "")
    owner, name = full.split("/", 1) if "/" in full else ("", full)
    project = await repo.get_by_git_repo("gitea", owner, name)
    if not project:
        project = await repo.get_by_id(full)
    if not project:
        logger.warning("No project config for %s", full)
        return {"status": "ignored", "reason": "unknown_project"}

    pr_number = int(issue.get("number") or 0)
    active = await db.execute(
        select(TaskRun.id)
        .where(
            TaskRun.project_id == project.project_id,
            TaskRun.task_id.like(f"pr-comment-{pr_number}-%"),
            TaskRun.status.in_(("pending", "running")),
        )
        .limit(1)
    )
    if active.scalar_one_or_none():
        return {"status": "ignored", "reason": "fix_in_progress"}

    token = await get_project_token(
        SimpleNamespace(
            git_provider="gitea",
            project_id=project.project_id,
            workspace_server_id=getattr(project, "workspace_server_id", None),
        ),
        db,
    )
    provider = get_git_provider("gitea", get_http_client(), access_token=token)
    api = f"{provider._base_url}/api/v1/repos/{full}"
    resp = await provider._client.get(f"{api}/pulls/{pr_number}", headers=provider._headers(), timeout=30.0)
    resp.raise_for_status()
    pr = resp.json()
    if pr.get("state") != "open" or pr.get("merged"):
        return {"status": "ignored", "reason": "pr_not_open"}
    head = pr.get("head") or {}
    pr_branch = head.get("ref") or ""
    if not pr_branch or (head.get("repo") or {}).get("full_name", full) != full:
        return {"status": "ignored", "reason": "pr_branch_not_in_repo"}

    m = re.search(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", pr.get("body") or "")
    issue_no = int(m.group(1)) if m else None
    labels = [la.get("name", "") for la in pr.get("labels") or []]
    # bimetri yamasi: status/on-hold iken otomatik tur acilmaz; insanin @agentickode yorumu acar (kosu etiketi kaldirir)
    if "status/on-hold" in labels and "<!-- agentickode-oto -->" in comment_body:
        return {"status": "ignored", "reason": "on_hold"}
    if issue_no:  # ajan/zorluk etiketleri issue'dan gelsin
        r = await provider._client.get(f"{api}/issues/{issue_no}", headers=provider._headers(), timeout=30.0)
        if r.status_code == 200:
            labels += [la.get("name", "") for la in r.json().get("labels") or []]

    instruction = comment_body
    for trigger in _MENTION_TRIGGERS:
        instruction = re.sub(re.escape(trigger), "", instruction, flags=re.IGNORECASE)
    instruction = instruction.strip() or f"PR #{pr_number} uzerindeki yorumlari ele al"
    alinti = "> " + comment_body.strip().replace("\n", "\n> ")
    login = (comment.get("user") or {}).get("login", "?")

    run = create_task_run(
        task_id=f"pr-comment-{pr_number}-{comment.get('id', '')}",
        project=project,
        title=f"[PR #{pr_number}] {instruction[:80]}",
        description=(
            f"Gitea PR #{pr_number} (**{pr.get('title', '')}**) uzerine {login} su yorumu yazdi:\n\n"
            f"{alinti}\n\n"
            f"Bu PR'in dalindasin (`{pr_branch}`); yeni dal acma. Yalnizca yorumda isteneni yap, "
            "AGENTS.md kurallarina gore commit et. Son mesajinda ne degistirdigini Turkce ozetle; "
            "bu mesaj PR'a yorum olarak yazilir."
        ),
        task_source="gitea",
        task_source_meta={
            "repo_full_name": full,
            "issue_number": issue_no,
            "pr_number": pr_number,
            "pr_head_branch": pr_branch,
            "pr_url": pr.get("html_url"),
            "review_mode": "fix",
            "comment_id": comment.get("id"),
            "trigger": "pr_comment",
            "labels": labels,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    logger.info("Created fix run #%d from Gitea PR comment on %s#%d", run.id, full, pr_number)
    return {"status": "accepted", "run_id": run.id}


@router.post("/webhooks/github-pr-comment")
async def github_pr_comment_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    repo: ProjectConfigRepository = Depends(_get_repo),
):
    """Receive GitHub issue_comment events on PRs with @agentickode mention."""
    body = await request.json()
    action = body.get("action", "")
    if action != "created":
        return {"status": "ignored", "reason": f"action_{action}"}

    comment = body.get("comment", {})
    comment_body = comment.get("body", "")

    # Check if comment mentions the agent
    comment_lower = comment_body.lower()
    if not any(trigger in comment_lower for trigger in _MENTION_TRIGGERS):
        return {"status": "ignored", "reason": "no_mention"}

    # Must be on a PR (issue with pull_request key)
    issue = body.get("issue", {})
    if "pull_request" not in issue:
        return {"status": "ignored", "reason": "not_pr"}

    repo_data = body.get("repository", {})
    repo_full_name = repo_data.get("full_name", "")
    owner, name = repo_full_name.split("/", 1) if "/" in repo_full_name else ("", repo_full_name)

    project = await repo.get_by_git_repo("github", owner, name)
    if not project:
        project = await repo.get_by_id(repo_full_name)
    if not project:
        logger.warning("No project config for %s", repo_full_name)
        return {"status": "ignored", "reason": "unknown_project"}

    pr_number = issue.get("number", "")
    pr_title = issue.get("title", "")
    pr_branch = (issue.get("pull_request") or {}).get("head", {}).get("ref", "")

    # Strip the @mention from the comment to get the actual instruction
    instruction = comment_body
    for trigger in _MENTION_TRIGGERS:
        instruction = instruction.replace(trigger, "").replace(trigger.upper(), "")
    instruction = instruction.strip()
    if not instruction:
        instruction = f"Address the review comment on PR #{pr_number}"

    run = create_task_run(
        task_id=f"pr-comment-{pr_number}-{comment.get('id', '')}",
        project=project,
        title=f"[PR #{pr_number}] {instruction[:80]}",
        description=(
            f"PR review comment on **{pr_title}** (#{pr_number}):\n\n"
            f"> {comment_body}\n\n"
            f"Commenter: {comment.get('user', {}).get('login', 'unknown')}\n"
            f"PR branch: `{pr_branch}`"
        ),
        task_source="github",
        task_source_meta={
            "repo_full_name": repo_full_name,
            "issue_number": pr_number,
            "pr_number": pr_number,
            "pr_branch": pr_branch,
            "comment_id": comment.get("id"),
            "trigger": "pr_comment",
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    logger.info("Created run #%d from PR comment on %s#%d", run.id, repo_full_name, pr_number)
    return {"status": "accepted", "run_id": run.id}

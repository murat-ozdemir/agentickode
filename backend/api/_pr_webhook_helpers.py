# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""Shared helpers for the PR-review webhook + CI trigger endpoints."""

import json
import logging

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ProjectConfig, TaskRun
from backend.repositories.project_config_repo import ProjectConfigRepository
from backend.services.run_factory import create_task_run
from backend.services.webhook_security import verify_hmac_sha256

logger = logging.getLogger("agentickode.webhooks")

# PR actions worth reviewing (others — e.g. closed/assigned — are ignored).
GITHUB_PR_ACTIONS = {"opened", "synchronize", "reopened", "labeled", "ready_for_review"}
GITEA_PR_ACTIONS = {"opened", "synchronized", "reopened", "label_updated"}

# Statuses for which a review is still in-flight (used to dedupe rapid PR events).
_ACTIVE_RUN_STATUSES = ("pending", "running")


async def read_verified_body(request: Request, secret: str, signature_header: str) -> dict:
    """Read the raw body, verifying the HMAC signature when a secret is set."""
    raw = await request.body()
    if secret and not verify_hmac_sha256(secret, raw, request.headers.get(signature_header)):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    try:
        return json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc


async def _active_review_exists(db: AsyncSession, project_id: str, task_id: str) -> bool:
    """True if a review run for this project + PR is already pending/running."""
    result = await db.execute(
        select(TaskRun.id).where(
            TaskRun.project_id == project_id,
            TaskRun.task_id == task_id,
            TaskRun.status.in_(_ACTIVE_RUN_STATUSES),
        )
    )
    return result.scalar_one_or_none() is not None


def build_pr_review_run(
    project: ProjectConfig,
    *,
    task_source: str,
    pr_number: int,
    pr_title: str,
    pr_body: str,
    pr_head_branch: str,
    pr_url: str,
    repo_full_name: str,
    labels: list[str],
    pr_head_sha: str = "",
    flow_prompt_id: int | None = None,
) -> TaskRun:
    """Create a single-pass, comment-mode PR-review run (ADR-009 flow prompt).

    Bound to the ``pr_review`` flow prompt when ``flow_prompt_id`` is provided;
    otherwise the dispatcher resolves it from the run's ``review_mode`` meta.
    """
    run = create_task_run(
        task_id=f"pr-{pr_number}",
        project=project,
        title=f"Review PR #{pr_number}: {pr_title}",
        description=pr_body or "",
        task_source=task_source,
        task_source_meta={
            "pr_url": pr_url,
            "pr_number": pr_number,
            "pr_title": pr_title,
            "pr_head_branch": pr_head_branch,
            "pr_head_sha": pr_head_sha,
            "repo_full_name": repo_full_name,
            "labels": labels,
            "review_mode": "comment",
        },
        use_claude=False,
        flow_prompt_id=flow_prompt_id,
    )
    run.max_retries = 0  # single-pass review — never auto-fix an un-checked-out workspace
    return run


async def resolve_pr_review_flow_prompt_id(db) -> int | None:
    """The ``pr_review`` flow prompt id, or None when it isn't seeded.

    ADR-009: PR-review always runs the single-agent-call flow path. None is a
    safe fallback — the dispatcher resolves the flow from the run's
    ``review_mode`` meta.
    """
    from backend.repositories.flow_prompt_repo import FlowPromptRepository

    flow = await FlowPromptRepository(db).get_by_flow_type("pr_review")
    return int(flow.id) if flow else None


# bimetri yamasi: merge edilen PR'a ve aciklamasindaki "Closes #N" issue'larina status/completed
async def _bimetri_pr_merged(body: dict, db: AsyncSession, repo: ProjectConfigRepository) -> dict:
    import re
    from types import SimpleNamespace

    from backend.services.git import get_git_provider
    from backend.services.http_client import get_http_client
    from backend.worker.phases._helpers import get_project_token

    pr = body.get("pull_request") or {}
    full = body.get("repository", {}).get("full_name", "")
    owner, name = full.split("/", 1) if "/" in full else ("", full)
    project = await repo.get_by_git_repo("gitea", owner, name)
    if not project:
        project = await repo.get_by_id(full)
    if not project:
        return {"status": "ignored", "reason": "unknown_project"}
    pattern = r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)"
    issues = sorted({int(n) for n in re.findall(pattern, pr.get("body") or "")})
    if pr.get("number"):  # PR'in kendisi de etiketlensin
        issues.append(int(pr["number"]))
    token = await get_project_token(
        SimpleNamespace(
            git_provider="gitea",
            project_id=project.project_id,
            workspace_server_id=getattr(project, "workspace_server_id", None),
        ),
        db,
    )
    provider = get_git_provider("gitea", get_http_client(), access_token=token)
    done = []
    for n in issues:
        try:
            await provider.set_status_label(full, n, "status/completed")
            done.append(n)
        except Exception:
            logger.warning("#%s status/completed etiketlenemedi", n, exc_info=True)
    return {"status": "accepted", "completed": done}


# bimetri yamasi: ai-test etiketi PR dalinda test kosusu acar (review_mode=test); status/on-hold iken acmaz
async def _bimetri_test_run(
    body: dict, db: AsyncSession, project: ProjectConfig, label_names: list[str]
) -> dict:
    import re

    pr = body.get("pull_request") or {}
    full = body.get("repository", {}).get("full_name", "")
    pr_number = int(pr.get("number") or 0)
    if pr.get("state") != "open" or pr.get("merged"):
        return {"status": "ignored", "reason": "pr_not_open"}
    if "status/on-hold" in label_names:
        return {"status": "ignored", "reason": "on_hold"}
    head = pr.get("head") or {}
    branch = head.get("ref") or ""
    if not branch or (head.get("repo") or {}).get("full_name", full) != full:
        return {"status": "ignored", "reason": "pr_branch_not_in_repo"}
    if await _active_review_exists(db, project.project_id, f"pr-test-{pr_number}"):
        return {"status": "ignored", "reason": "test_in_progress"}
    m = re.search(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", pr.get("body") or "")
    issue_no = int(m.group(1)) if m else None
    base = (pr.get("base") or {}).get("ref") or "main"
    pr_body = (pr.get("body") or "").strip()[:4000]
    run = create_task_run(
        task_id=f"pr-test-{pr_number}",
        project=project,
        title=f"[PR #{pr_number}] Test: {(pr.get('title') or '')[:80]}",
        description=(
            f"Gitea PR #{pr_number} (**{pr.get('title', '')}**) icin testleri yaz ve calistir.\n\n"
            f"Bu PR'in dalindasin (`{branch}`); yeni dal acma. PR'daki degisiklik: "
            f"`git diff origin/{base}...HEAD`.\n"
            + (f"Bagli issue: #{issue_no}; commit mesajinda `(#{issue_no})` kullan.\n" if issue_no else "")
            + (f"\nPR aciklamasi:\n\n{pr_body}\n" if pr_body else "")
        ),
        task_source="gitea",
        task_source_meta={
            "repo_full_name": full,
            "issue_number": issue_no,
            "pr_number": pr_number,
            "pr_head_branch": branch,
            "pr_url": pr.get("html_url"),
            "review_mode": "test",
            "trigger": "ai_test",
            "labels": label_names,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    logger.info("Created test run #%d from Gitea PR #%d (%s)", run.id, pr_number, full)
    return {"status": "accepted", "run_id": run.id}


async def handle_pr_event(
    request: Request,
    db: AsyncSession,
    repo: ProjectConfigRepository,
    *,
    source: str,
    allowed_actions: set[str],
    secret: str,
    signature_header: str,
) -> dict:
    """Parse a provider ``pull_request`` event and launch a review when matched."""
    body = await read_verified_body(request, secret, signature_header)
    action = body.get("action", "")
    # bimetri yamasi: Gitea'da PR merge edilince bagli issue status/completed
    if source == "gitea" and action == "closed" and (body.get("pull_request") or {}).get("merged"):
        return await _bimetri_pr_merged(body, db, repo)
    if action not in allowed_actions:
        return {"status": "ignored", "reason": f"action_{action}"}

    pr = body.get("pull_request", {})
    repo_full_name = body.get("repository", {}).get("full_name", "")
    owner, name = repo_full_name.split("/", 1) if "/" in repo_full_name else ("", repo_full_name)

    project = await repo.get_by_git_repo(source, owner, name)
    if not project:
        project = await repo.get_by_id(repo_full_name)  # parity with issue webhook
    if not project:
        logger.warning("No project config for %s", repo_full_name)
        return {"status": "ignored", "reason": "unknown_project"}

    label_names = [lbl.get("name", "") for lbl in pr.get("labels", [])]
    # bimetri yamasi: bot push'u yok sayilir; insan push'u botun PR'inda testi yeniden baslatir
    if source == "gitea" and action == "synchronized":
        try:
            from backend.api._bimetri_push import proje_saglayici, push_karari

            karar = await push_karari(await proje_saglayici(project, db), body, label_names)
            if karar:
                return karar
        except Exception:
            logger.warning("Push karari verilemedi (%s)", repo_full_name, exc_info=True)
    # bimetri yamasi: ai-test once gelir (inceleme testten sonra); push (synchronized) test baslatmaz
    if source == "gitea" and "ai-test" in label_names:
        if action == "synchronized":
            return {"status": "ignored", "reason": "test_not_on_push"}
        return await _bimetri_test_run(body, db, project, label_names)
    # PR-review is opt-in via the ``ai-review`` label (ADR-009: the run dispatches
    # to the pr_review flow prompt).
    if "ai-review" not in label_names:
        return {"status": "ignored", "reason": "no_ai_review_label"}

    pr_number = pr.get("number", 0)
    if await _active_review_exists(db, project.project_id, f"pr-{pr_number}"):
        logger.info("Review already in-flight for %s PR #%s — skipping", source, pr_number)
        return {"status": "ignored", "reason": "review_in_progress"}

    run = build_pr_review_run(
        project,
        task_source=source,
        pr_number=pr_number,
        pr_title=pr.get("title", ""),
        pr_body=pr.get("body", "") or "",
        pr_head_branch=pr.get("head", {}).get("ref", ""),
        pr_url=pr.get("html_url", ""),
        repo_full_name=repo_full_name,
        labels=label_names,
        flow_prompt_id=await resolve_pr_review_flow_prompt_id(db),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    logger.info("Created run #%d from %s PR webhook: %s", run.id, source, run.title)
    return {"status": "accepted", "run_id": run.id}

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""Phase 6: Finalization — confirm PR is open, cleanup sandbox.

The PR is created during the approval phase. Finalization does NOT auto-merge;
the human reviewer merges via the git provider UI after reviewing the PR.

For pr-review workflows, posts the AI review as a comment on the source PR.
"""

import logging
import shlex

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskRun
from backend.services.container import ServiceContainer
from backend.services.git import RemoteGitOps, get_git_provider
from backend.services.git.ops import get_repo_https_url
from backend.services.http_client import get_http_client
from backend.services.workspace.sandbox import RemoteSandbox
from backend.services.workspace.worktree import WorktreeManager, WorktreePaths
from backend.worker.broadcaster import broadcaster
from backend.worker.phases._helpers import (
    close_run_session,
    get_auth_url,
    get_project_token,
    get_ssh_for_run,
)

logger = logging.getLogger("agentickode.phases.finalization")

PHASE_META = {
    "kind": "legacy_phase",
    "deprecated_in": "0.5.0",
    "description": "Confirm PR and clean up resources",
}


async def run(
    task_run: TaskRun,
    session: AsyncSession,
    services: ServiceContainer,
    phase_config: dict | None = None,
) -> None:
    meta = task_run.task_source_meta or {}
    pr_number = meta.get("pr_number")
    pr_branch = meta.get("pr_head_branch")
    review_mode = meta.get("review_mode")

    # fix-pr: push fixes to existing PR branch (no new PR). Only for explicit
    # fix-mode runs — a comment-only PR review must never push to the PR branch
    # (it has no checkout/commits and pushing would fail or clobber the branch).
    if pr_branch and not task_run.pr_url and review_mode == "fix":
        # bimetri yamasi: duzeltme kosusu (PR yorumu) - kalan degisikligi commit'le, PR dalina push et, PR'a yorum yaz
        _git = RemoteGitOps(await get_ssh_for_run(task_run, session))
        _cwd = task_run.workspace_path
        if (await _git.run_git(["status", "--porcelain"], cwd=_cwd)).stdout.strip():
            await _git.run_git(["add", "-A"], cwd=_cwd)
            await _git.run_git(
                ["-c", "user.name=AgenticKode", "-c", "user.email=agentickode@localhost",
                 "commit", "-m", f"fix: PR #{pr_number} yorumundaki istek"],
                cwd=_cwd,
            )
        _ahead = (
            await _git.run_git(["rev-list", "--count", f"origin/{pr_branch}..HEAD"], cwd=_cwd)
        ).stdout.strip()
        if not _ahead or _ahead == "0":
            raise RuntimeError("Duzeltme kosusu: ajan degisiklik birakmadi, PR dalina push edilmedi")
        await _push_to_pr_branch(task_run, pr_branch, session)
        task_run.pr_url = meta.get("pr_url") or None
        await session.commit()
        try:  # yeni commit'ler yeniden incelensin: ai-reviewed -> ai-review (label_updated tetikler)
            _gp = get_git_provider(
                task_run.git_provider, get_http_client(), access_token=await get_project_token(task_run, session)
            )
            _rp = f"{task_run.repo_owner}/{task_run.repo_name}"
            await _gp.remove_label(_rp, int(pr_number), "ai-reviewed")
            await _gp.add_label(_rp, int(pr_number), "ai-review")
        except Exception as exc:
            await broadcaster.log(
                task_run.id, f"PR ai-review etiketi geri konamadi: {exc}", level="warning", phase="finalization"
            )
        try:
            from backend.config import settings as _settings

            _ozet = (task_run.coding_results or {}).get("response") or ""
            if isinstance(_ozet, dict):  # CLI ajani: yalnizca son mesaj
                _ozet = _ozet.get("output") or ""
            _ozet = (_ozet if isinstance(_ozet, str) else str(_ozet)).strip()[:6000]
            _kosu = f"{_settings.app_base_url.rstrip('/')}/runs/{task_run.id}"
            _govde = (
                f"## Düzeltme push edildi ({_ahead} commit)\n\n"
                + (_ozet or "_Ajan özet bırakmadı._")
                + f"\n\n---\nKoşu: [#{task_run.id}]({_kosu}) · AgenticKode"
            ).replace("@", "@​")  # kendi yorumu yeni kosu tetiklemesin
            await get_git_provider(
                task_run.git_provider,
                get_http_client(),
                access_token=await get_project_token(task_run, session),
            ).post_pr_comment(f"{task_run.repo_owner}/{task_run.repo_name}", int(pr_number), _govde)
        except Exception as exc:
            await broadcaster.log(
                task_run.id, f"PR'a yorum yazilamadi: {exc}", level="warning", phase="finalization"
            )

    # Post review comment on source PR for pr-review / fix-pr workflows
    if task_run.review_result and pr_number:
        await _post_review_comment(task_run, pr_number, session)
        # Flip the label to mark the PR as reviewed (visible marker; the DB head
        # SHA remains the source of truth the poller dedupes on).
        if review_mode == "comment":
            await _flip_review_label(task_run, pr_number, session)

    # bimetri yamasi: ajan commit/push etmediyse degisiklikleri commit'leyip push et; bos kosuda PR yok
    bos_kosu = False
    if not task_run.pr_url and not pr_number and task_run.branch_name and task_run.workspace_path:
        try:
            ssh = await get_ssh_for_run(task_run, session)
            git = RemoteGitOps(ssh)
            cwd = task_run.workspace_path
            if (await git.run_git(["status", "--porcelain"], cwd=cwd)).stdout.strip():
                await git.run_git(["add", "-A"], cwd=cwd)
                await git.run_git(
                    ["-c", "user.name=AgenticKode", "-c", "user.email=agentickode@localhost",
                     "commit", "-m", task_run.title or task_run.branch_name],
                    cwd=cwd,
                )
                await broadcaster.log(
                    task_run.id, "Ajanin biraktigi degisiklikler commit'lendi", phase="finalization"
                )
            ahead = (
                await git.run_git(
                    ["rev-list", "--count", f"origin/{task_run.default_branch}..HEAD"], cwd=cwd
                )
            ).stdout.strip()
            if ahead and ahead != "0":
                auth_url, method = await get_auth_url(
                    get_repo_https_url(task_run.git_provider, task_run.repo_owner, task_run.repo_name),
                    task_run.git_provider,
                    ssh,
                    token_override=await get_project_token(task_run, session),
                )
                await git.run_git(["remote", "set-url", "origin", auth_url], cwd=cwd)
                await git.run_git(
                    ["push", "-u", "origin", f"HEAD:refs/heads/{task_run.branch_name}"], cwd=cwd
                )
                await broadcaster.log(
                    task_run.id,
                    f"{task_run.branch_name} push edildi ({ahead} commit, auth={method})",
                    phase="finalization",
                )
            else:
                bos_kosu = True
                await broadcaster.log(
                    task_run.id,
                    "Ajan hicbir degisiklik birakmadi; PR acilmayacak",
                    level="warning",
                    phase="finalization",
                )
        except Exception as exc:
            await broadcaster.log(
                task_run.id, f"Branch push edilemedi: {exc}", level="warning", phase="finalization"
            )

    # bimetri yamasi: degisiklik push edildiyse ve PR yoksa PR'i platform acsin
    if not task_run.pr_url and not pr_number and task_run.branch_name and not bos_kosu:
        issue_no = meta.get("issue_number")
        try:
            provider = get_git_provider(
                task_run.git_provider,
                get_http_client(),
                access_token=await get_project_token(task_run, session),
            )
            task_run.pr_url = await provider.create_pr(
                f"{task_run.repo_owner}/{task_run.repo_name}",
                task_run.title,
                (f"Closes #{issue_no}\n\n" if issue_no else "")
                + "AgenticKode tarafindan acildi.",
                task_run.branch_name,
                task_run.default_branch,
            ) or None
            await session.commit()
            # bimetri yamasi: PR'in dalini issue'nun "Branch/Tag" alanina bagla
            if task_run.pr_url and issue_no and task_run.git_provider == "gitea":
                try:
                    _r = await provider._client.patch(
                        f"{provider._base_url}/api/v1/repos/{task_run.repo_owner}/"
                        f"{task_run.repo_name}/issues/{issue_no}",
                        headers=provider._headers(),
                        json={"ref": f"refs/heads/{task_run.branch_name}"},
                        timeout=30.0,
                    )
                    _r.raise_for_status()
                    await broadcaster.log(
                        task_run.id,
                        f"Issue #{issue_no} dali: {task_run.branch_name}",
                        phase="finalization",
                    )
                except Exception as exc:
                    await broadcaster.log(
                        task_run.id,
                        f"Issue dali ayarlanamadi: {exc}",
                        level="warning",
                        phase="finalization",
                    )
        except Exception as exc:
            await broadcaster.log(
                task_run.id, f"PR acilamadi: {exc}", level="warning", phase="finalization"
            )

    # bimetri yamasi: PR'i ajan actiysa aciklamaya "Closes #N" ekle, merge'de issue kapansin
    issue_no = meta.get("issue_number")
    if task_run.pr_url and issue_no and task_run.git_provider == "gitea":
        try:
            import re

            provider = get_git_provider(
                task_run.git_provider,
                get_http_client(),
                access_token=await get_project_token(task_run, session),
            )
            pr_no = task_run.pr_url.rstrip("/").rsplit("/", 1)[-1]
            api = (
                f"{provider._base_url}/api/v1/repos/"
                f"{task_run.repo_owner}/{task_run.repo_name}/pulls/{pr_no}"
            )
            resp = await provider._client.get(api, headers=provider._headers(), timeout=30.0)
            resp.raise_for_status()
            body = resp.json().get("body") or ""
            if not re.search(rf"(?i)\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s+#{issue_no}\b", body):
                resp = await provider._client.patch(
                    api,
                    headers=provider._headers(),
                    json={"body": f"Closes #{issue_no}\n\n{body}"},
                    timeout=30.0,
                )
                resp.raise_for_status()
                await broadcaster.log(
                    task_run.id, f"PR aciklamasina 'Closes #{issue_no}' eklendi", phase="finalization"
                )
        except Exception as exc:
            await broadcaster.log(
                task_run.id, f"PR aciklamasi guncellenemedi: {exc}", level="warning", phase="finalization"
            )

    if task_run.pr_url:
        await broadcaster.log(
            task_run.id,
            f"PR ready for human review: {task_run.pr_url}",
            phase="finalization",
        )
    elif not pr_number:
        await broadcaster.log(task_run.id, "No PR URL found", level="warning", phase="finalization")

    # Close agent session (release locks so session_id can be reused if needed)
    await close_run_session(task_run, session)

    # Comment-mode PR reviews never set up a per-task workspace/sandbox (the diff
    # is fetched via API and reviewed in generate mode), so there is nothing to
    # tear down — skip the SSH cleanup so a successful review can't be failed by
    # a cleanup hiccup.
    if review_mode == "comment":
        await broadcaster.log(task_run.id, "Review complete", phase="finalization")
        return

    # Cleanup workspace
    await broadcaster.log(task_run.id, "Stopping sandbox containers (if any)", phase="finalization")
    ssh = await get_ssh_for_run(task_run, session)
    remote_sandbox = RemoteSandbox(ssh)
    await remote_sandbox.stop_sandbox(task_run.workspace_path)

    # Tear down per-run worktree (when workspace_setup created one). We
    # do this BEFORE the generic ``rm -rf`` because rm-ing a registered
    # worktree dir without ``git worktree remove`` leaves the parent
    # repo's ``.git/worktrees/<name>`` admin entry behind — better to let
    # git handle removal cleanly. When ``keep_workspace=true`` on the
    # phase config the dir is preserved so an operator can inspect it.
    await _cleanup_worktree_if_any(task_run, ssh, phase_config)

    # Remove task-scoped workspace directory to free disk space.
    # Only delete if path ends with the task run ID (safety guard against
    # accidentally removing a shared base directory).
    ws_path = task_run.workspace_path
    parts = ws_path.split("/") if ws_path else []
    if ws_path and ws_path.endswith(f"/{task_run.id}") and len(parts) >= 4:
        await broadcaster.log(
            task_run.id, f"Removing task workspace: {ws_path}", phase="finalization"
        )
        await ssh.run_command(f"rm -rf {shlex.quote(ws_path)}", timeout=60)

    await broadcaster.log(task_run.id, "Cleanup complete", phase="finalization")


async def _cleanup_worktree_if_any(task_run: TaskRun, ssh, phase_config: dict | None) -> None:
    """Remove the per-run worktree if workspace_setup created one.

    No-op when:
      * workspace_setup did not record worktree paths (default strategy)
      * phase_config sets ``keep_workspace: true`` (debugging escape hatch)

    Errors are swallowed — finalization should never fail because of a
    cleanup hiccup; the orphan-cleanup scheduler will sweep stragglers.
    """
    worktree_meta = (task_run.workspace_result or {}).get("worktree_paths")
    if not isinstance(worktree_meta, dict):
        return
    keep = bool((phase_config or {}).get("keep_workspace"))
    if keep:
        await broadcaster.log(
            task_run.id,
            f"Keeping worktree {worktree_meta.get('worktree_dir')} for debugging",
            phase="finalization",
        )
        return
    try:
        paths = WorktreePaths(**worktree_meta)
    except TypeError:
        logger.warning(
            "run #%d: worktree_paths metadata has unexpected shape: %r",
            task_run.id,
            worktree_meta,
        )
        return
    try:
        await WorktreeManager(ssh).remove(paths)
        await broadcaster.log(
            task_run.id, f"Removed worktree {paths.worktree_dir}", phase="finalization"
        )
    except Exception as exc:
        logger.warning(
            "run #%d: worktree cleanup failed for %s: %s",
            task_run.id,
            paths.worktree_dir,
            exc,
        )


async def _push_to_pr_branch(task_run: TaskRun, pr_branch: str, session: AsyncSession) -> None:
    """Push fixes to the existing PR branch."""
    await broadcaster.log(
        task_run.id,
        f"Pushing fixes to PR branch {pr_branch}",
        phase="finalization",
    )
    ssh = await get_ssh_for_run(task_run, session)
    remote_git = RemoteGitOps(ssh)

    project_token = await get_project_token(task_run, session)
    base_url = get_repo_https_url(task_run.git_provider, task_run.repo_owner, task_run.repo_name)

    auth_url, method = await get_auth_url(
        base_url, task_run.git_provider, ssh, token_override=project_token
    )
    cwd = task_run.workspace_path
    await remote_git.run_git(["remote", "set-url", "origin", auth_url], cwd=cwd)
    await remote_git.run_git(["push", "origin", pr_branch], cwd=cwd)
    await broadcaster.log(
        task_run.id,
        f"Pushed to {pr_branch} (auth={method})",
        phase="finalization",
    )


async def _post_review_comment(task_run: TaskRun, pr_number: int, session: AsyncSession) -> None:
    """Post AI review results as a comment on the source PR."""
    repo_path = f"{task_run.repo_owner}/{task_run.repo_name}"
    body = _build_review_comment(task_run.review_result)

    project_token = await get_project_token(task_run, session)
    client = get_http_client()
    provider = get_git_provider(task_run.git_provider, client, access_token=project_token)
    try:
        await provider.post_pr_comment(repo_path, pr_number, body)
        await broadcaster.log(
            task_run.id,
            f"Posted review comment on PR #{pr_number}",
            phase="finalization",
        )
    except Exception as exc:
        await broadcaster.log(
            task_run.id,
            f"Failed to post review comment: {exc}",
            level="warning",
            phase="finalization",
        )


async def _flip_review_label(task_run: TaskRun, pr_number: int, session: AsyncSession) -> None:
    """Flip ``ai-review`` → ``ai-reviewed`` on the PR (best-effort visible marker)."""
    repo_path = f"{task_run.repo_owner}/{task_run.repo_name}"
    project_token = await get_project_token(task_run, session)
    provider = get_git_provider(
        task_run.git_provider, get_http_client(), access_token=project_token
    )
    try:
        await provider.remove_label(repo_path, pr_number, "ai-review")
        await provider.add_label(repo_path, pr_number, "ai-reviewed")
        await broadcaster.log(
            task_run.id,
            f"Marked PR #{pr_number} as ai-reviewed",
            phase="finalization",
        )
    except Exception as exc:
        await broadcaster.log(
            task_run.id,
            f"Could not flip review label on PR #{pr_number}: {exc}",
            level="warning",
            phase="finalization",
        )


def _build_review_comment(review: dict) -> str:
    """Build a markdown comment from the review result."""
    issues = review.get("issues", [])
    suggestions = review.get("suggestions", [])
    summary = review.get("summary", "")
    approved = review.get("approved", False)

    parts = ["## AI Code Review\n"]

    if summary:
        parts.append(f"{summary}\n")

    status = "Approved" if approved else "Changes Requested"
    parts.append(f"**Status**: {status}")
    parts.append(f"**Issues Found**: {len(issues)}")
    parts.append(f"**Suggestions**: {len(suggestions)}\n")

    if issues:
        parts.append("### Issues\n")
        for issue in issues:
            severity = issue.get("severity", "info")
            desc = issue.get("description", "")
            file = issue.get("file", "")
            line = issue.get("line", "")
            loc = f"`{file}:{line}`" if file and line else (f"`{file}`" if file else "")
            parts.append(f"- **[{severity}]** {loc} {desc}")
        parts.append("")

    if suggestions:
        parts.append("### Suggestions\n")
        for s in suggestions:
            if isinstance(s, dict):
                parts.append(f"- {s.get('description', str(s))}")
            else:
                parts.append(f"- {s}")
        parts.append("")

    parts.append("---")
    parts.append("*Generated by AI Development Infrastructure*")
    return "\n".join(parts)

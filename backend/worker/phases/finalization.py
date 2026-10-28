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
from backend.worker.phases._bimetri_duzeltme import DEGISIKLIK_YOK_NOTU, duzeltme_govdesi
from backend.worker.phases._bimetri_etiket import (
    etiketler,
    inceleme_baslat,
    inceleme_istendi,
    pr_acilis_etiketleri,
)
from backend.worker.phases._bimetri_oto import OTO_YORUM, oto_tur_karari
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
            # bimetri yamasi: ajanin gerekcesi PR'a yazilsin (yoksa yalnizca kosu gunlugunde kalir)
            await _bimetri_pr_yorumu(
                task_run,
                session,
                int(pr_number),
                duzeltme_govdesi(task_run, "Düzeltme: değişiklik yapılmadı", DEGISIKLIK_YOK_NOTU),
            )
            raise RuntimeError("Duzeltme kosusu: ajan degisiklik birakmadi, PR dalina push edilmedi")
        # bimetri yamasi: duzeltme test dosyalarina dokundu mu (push'tan once; sonra origin/<dal> ilerler)
        import re as _re

        _test_dokunan = [
            _y
            for _y in (
                await _git.run_git(["diff", "--name-only", f"origin/{pr_branch}..HEAD"], cwd=_cwd)
            ).stdout.splitlines()
            if _re.search(r"(^|/)src/test/", _y)
        ]
        _mvnw = bool((await _git.run_git(["ls-files", "mvnw"], cwd=_cwd)).stdout.strip())
        await _push_to_pr_branch(task_run, pr_branch, session)
        task_run.pr_url = meta.get("pr_url") or None
        await session.commit()
        # bimetri yamasi: duzeltmeden sonra zincir testten baslar (ai-test; mvnw yoksa ai-review)
        try:
            _gp = get_git_provider(
                task_run.git_provider, get_http_client(), access_token=await get_project_token(task_run, session)
            )
            _rp = f"{task_run.repo_owner}/{task_run.repo_name}"
            for _l in ("ai-review", "ai-reviewed", "ai-test", "ai-tested", "test/passed", "test/failed"):
                await _gp.remove_label(_rp, int(pr_number), _l)
            if _test_dokunan:
                await _gp.post_pr_comment(
                    _rp,
                    int(pr_number),
                    "## Düzeltme test dosyalarına dokundu\n\n"
                    + "\n".join(f"- `{_y}`" for _y in _test_dokunan[:20])
                    + "\n\nTest dosyalarını değiştirmek insan onayı ister; zincir durdu (`status/on-hold`). "
                    "Uygunsa `status/on-hold`'u kaldırıp `ai-test` koy.",
                )
            elif _mvnw:
                await _gp.add_label(_rp, int(pr_number), "ai-test")
            # bimetri yamasi: mvnw yoksa AI incelemesi yalnizca istendiyse (issue/PR'da ai-review)
            elif await inceleme_istendi(_gp, _rp, int(pr_number), meta.get("issue_number")):
                await _gp.add_label(_rp, int(pr_number), "ai-review")
        except Exception as exc:
            await broadcaster.log(
                task_run.id, f"PR test/inceleme etiketleri ayarlanamadi: {exc}", level="warning", phase="finalization"
            )
        await _bimetri_pr_yorumu(
            task_run, session, int(pr_number), duzeltme_govdesi(task_run, f"Düzeltme push edildi ({_ahead} commit)")
        )
        # bimetri yamasi: test dosyasina dokunan duzeltme kosusu basarisiz sayilir -> status/on-hold
        if _test_dokunan:
            raise RuntimeError(
                "Duzeltme test dosyalarina dokundu (" + ", ".join(_test_dokunan[:5]) + "); insan incelemesi gerekli"
            )

    # bimetri yamasi: test kosusu (ai-test) sonu: denetim, push, rapor, etiket zinciri
    if pr_branch and review_mode == "test":
        await _bimetri_test_finalize(task_run, int(pr_number), pr_branch, meta, session)

    # Post review comment on source PR for pr-review / fix-pr workflows
    if task_run.review_result and pr_number:
        # bimetri yamasi: "Değişiklik gerekli" incelemesi ajanin PR'inda otomatik duzeltme turu acar
        _oto = review_mode == "comment" and await _bimetri_oto_duzeltme(task_run, int(pr_number), session)
        await _post_review_comment(task_run, pr_number, session, _oto)
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
        # bimetri yamasi: PR aciklamasinda ajanin ozeti, ajan/model ve kosu baglantisi
        import json as _json

        from backend.config import settings as _settings

        _cr = task_run.coding_results or {}
        _ozet = _cr.get("response") or ""
        if isinstance(_ozet, dict):  # CLI ajani: {"output": son mesaj, "stderr": ..., ...}
            _ozet = _ozet.get("output") or ""
        if not isinstance(_ozet, str):
            _ozet = _json.dumps(_ozet, ensure_ascii=False, indent=2, default=str)
        _ozet = _ozet.strip()
        if len(_ozet) > 6000:
            _ozet = _ozet[:6000].rstrip() + "\n\n…(kısaltıldı, tamamı koşu logunda)"
        _kosu = f"{_settings.app_base_url.rstrip('/')}/runs/{task_run.id}"
        pr_govdesi = (
            (f"Closes #{issue_no}\n\n" if issue_no else "")
            + "## Ajanın özeti\n\n"
            + (_ozet or "_Ajan özet bırakmadı._")
            + "\n\n---\n"
            + f"Ajan: {_cr.get('agent') or '?'}"
            + (f" · Model: {_cr['model']}" if _cr.get("model") else "")
            + f" · Koşu: [#{task_run.id}]({_kosu})\n\n"
            + "AgenticKode tarafından açıldı."
        )
        try:
            provider = get_git_provider(
                task_run.git_provider,
                get_http_client(),
                access_token=await get_project_token(task_run, session),
            )
            task_run.pr_url = await provider.create_pr(
                f"{task_run.repo_owner}/{task_run.repo_name}",
                task_run.title,
                # bimetri yamasi: aciklama yukarida hazirlandi (pr_govdesi)
                pr_govdesi,
                task_run.branch_name,
                task_run.default_branch,
            ) or None
            await session.commit()
            # bimetri yamasi: yeni PR'a difficulty/*, test-agent/* ve ai-test (mvnw varsa) ya da ai-review
            if task_run.pr_url and task_run.git_provider == "gitea":
                try:
                    _mvnw = await RemoteGitOps(await get_ssh_for_run(task_run, session)).run_git(
                        ["ls-files", "mvnw"], cwd=task_run.workspace_path
                    )
                    _konan = await pr_acilis_etiketleri(
                        provider,
                        f"{task_run.repo_owner}/{task_run.repo_name}",
                        int(task_run.pr_url.rstrip("/").rsplit("/", 1)[-1]),
                        issue_no,
                        _cr.get("agent"),
                        bool(_mvnw.stdout.strip()),
                    )
                    await broadcaster.log(
                        task_run.id, f"PR etiketleri: {', '.join(_konan) or 'yok'}", phase="finalization"
                    )
                except Exception as exc:
                    await broadcaster.log(
                        task_run.id, f"PR etiketleri konamadi: {exc}", level="warning", phase="finalization"
                    )
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


async def _bimetri_oto_duzeltme(task_run: TaskRun, n: int, session: AsyncSession) -> bool:
    ozet = str((task_run.review_result or {}).get("summary") or "")
    if task_run.git_provider != "gitea" or "Değişiklik gerekli" not in ozet[-400:]:
        return False
    gp = get_git_provider(task_run.git_provider, get_http_client(), access_token=await get_project_token(task_run, session))
    return await oto_tur_karari(
        gp, f"{task_run.repo_owner}/{task_run.repo_name}", n, "inceleme değişiklik istedi", task_run.id
    )


async def _bimetri_pr_yorumu(task_run: TaskRun, session: AsyncSession, n: int, govde: str) -> None:
    try:
        await get_git_provider(
            task_run.git_provider, get_http_client(), access_token=await get_project_token(task_run, session)
        ).post_pr_comment(f"{task_run.repo_owner}/{task_run.repo_name}", n, govde)
    except Exception as exc:
        await broadcaster.log(task_run.id, f"PR'a yorum yazilamadi: {exc}", level="warning", phase="finalization")


async def _bimetri_test_finalize(task_run: TaskRun, n: int, pr_branch: str, meta: dict, session: AsyncSession) -> None:
    import contextlib
    import re

    from backend.config import settings as _settings

    rp = f"{task_run.repo_owner}/{task_run.repo_name}"
    gp = get_git_provider(task_run.git_provider, get_http_client(), access_token=await get_project_token(task_run, session))
    # bimetri yamasi: insan test surerken ai-review koyduysa hatirla; ai-test'ten once kaldir ki
    # ai-test kalkinca inceleme test sonucunu beklemeden baslamasin
    pr_ai_review = "ai-review" in await etiketler(gp, rp, n)
    # once ai-test kalksin: bundan sonraki etiket degisiklikleri yeni test kosusu acmasin
    for _l in ("ai-review", "ai-test", "test/passed", "test/failed"):
        with contextlib.suppress(Exception):
            await gp.remove_label(rp, n, _l)
    with contextlib.suppress(Exception):
        await gp.add_label(rp, n, "ai-tested")
    task_run.pr_url = meta.get("pr_url") or None

    git = RemoteGitOps(await get_ssh_for_run(task_run, session))
    cwd = task_run.workspace_path
    if (await git.run_git(["status", "--porcelain"], cwd=cwd)).stdout.strip():
        await git.run_git(["add", "-A"], cwd=cwd)
        issue_no = meta.get("issue_number")
        await git.run_git(
            ["-c", "user.name=AgenticKode", "-c", "user.email=agentickode@localhost",
             "commit", "-m", f"test: PR #{n} testleri" + (f" (#{issue_no})" if issue_no else "")],
            cwd=cwd,
        )
    # kural denetimi: yalnizca src/test/**, test silme yok, @Disabled/@Ignore yok
    ihlal = []
    for satir in (await git.run_git(["diff", "--name-status", f"origin/{pr_branch}..HEAD"], cwd=cwd)).stdout.splitlines():
        durum, *yollar = satir.split("\t")
        for y in yollar:
            if not re.search(r"(^|/)src/test/", y):
                ihlal.append(f"test klasörü dışında değişiklik: `{y}`")
            elif durum.startswith("D"):
                ihlal.append(f"test silindi: `{y}`")
    fark = (await git.run_git(["diff", "-U0", f"origin/{pr_branch}..HEAD"], cwd=cwd)).stdout
    if re.search(r"(?m)^\+(?!\+\+).*@(Disabled|Ignore)\b", fark):
        ihlal.append("`@Disabled` / `@Ignore` eklendi")
    # bimetri yamasi: degisen test dosyalarinda kaybolan @Test metotlari (silinmis ya da adi degismis)
    _test_rx = re.compile(
        r"@(?:Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b[^{;]*?\bvoid\s+(\w+)\s*\(", re.S
    )
    kaybolan = []
    _degisen = (await git.run_git(
        ["diff", "--name-only", "--diff-filter=M", f"origin/{pr_branch}..HEAD"], cwd=cwd
    )).stdout.splitlines()
    for y in (y for y in _degisen if re.search(r"(^|/)src/test/", y)):
        try:
            _once = (await git.run_git(["show", f"origin/{pr_branch}:{y}"], cwd=cwd)).stdout
            _sonra = (await git.run_git(["show", f"HEAD:{y}"], cwd=cwd)).stdout
        except Exception:
            continue
        kaybolan += [f"`{y.rsplit('/', 1)[-1]}#{a}`" for a in sorted(set(_test_rx.findall(_once)) - set(_test_rx.findall(_sonra)))]
    ahead = (await git.run_git(["rev-list", "--count", f"origin/{pr_branch}..HEAD"], cwd=cwd)).stdout.strip()

    rapor = (task_run.coding_results or {}).get("response") or ""
    if isinstance(rapor, dict):  # CLI ajani: yalnizca son mesaj
        rapor = rapor.get("output") or ""
    rapor = (rapor if isinstance(rapor, str) else str(rapor)).strip()
    m = re.search(r"\*\*Sonuç:\*\*\s*(Testler geçti|Testler kaldı|Test edilemedi)", rapor[-400:])
    sonuc = m.group(1) if m else "Test edilemedi"
    if ihlal:
        sonuc = "Kural ihlali"
    elif ahead and ahead != "0":
        await _push_to_pr_branch(task_run, pr_branch, session)

    _kosu = f"{_settings.app_base_url.rstrip('/')}/runs/{task_run.id}"
    govde = (
        "## AI Test Raporu\n\n"
        + (
            "**Kural ihlali; testler push edilmedi:**\n" + "\n".join(f"- {i}" for i in ihlal) + "\n\n"
            if ihlal else ""
        )
        # bimetri yamasi: kaybolan test metotlari uyarisi (kosuyu durdurmaz)
        + (
            "**Uyarı: test ajanı mevcut test metotlarını sildi ya da adlarını değiştirdi:** "
            + ", ".join(kaybolan)
            + ". Eski testlerin kapsadığı durumların yeni testlerde olup olmadığına bakın.\n\n"
            if kaybolan else ""
        )
        + (rapor[:12000] or "_Ajan rapor bırakmadı._")
        + ("" if m else "\n\n_Rapor sonuç satırı içermiyor; 'Test edilemedi' sayıldı._")
        # bimetri yamasi: test raporunda da ajan ve model (kod PR'indaki gibi)
        + "\n\n---\n"
        + f"Ajan: {(task_run.coding_results or {}).get('agent') or '?'}"
        + (f" · Model: {task_run.coding_results['model']}" if (task_run.coding_results or {}).get("model") else "")
        + f" · Koşu: [#{task_run.id}]({_kosu}) · AgenticKode"
    ).replace("@", "@​")
    oto = sonuc == "Testler kaldı" and await oto_tur_karari(
        gp, rp, n, "test ajanı başarısız testler buldu", task_run.id
    )
    if oto:
        govde = OTO_YORUM.format(neden="Test ajanı başarısız testler buldu (rapor aşağıda).") + govde
    try:
        await gp.post_pr_comment(rp, n, govde)
    except Exception as exc:
        await broadcaster.log(task_run.id, f"Test raporu yazilamadi: {exc}", level="warning", phase="finalization")
    await broadcaster.log(task_run.id, f"Test sonucu: {sonuc}", phase="finalization")

    if sonuc == "Testler geçti":
        await gp.add_label(rp, n, "test/passed")
        # bimetri yamasi: AI incelemesi istege bagli; istenmediyse PR status/review'da insani bekler
        if pr_ai_review or await inceleme_istendi(gp, rp, n, meta.get("issue_number")):
            await inceleme_baslat(gp, rp, n)  # label_updated -> inceleme
        else:
            await broadcaster.log(task_run.id, "AI incelemesi istenmedi; insan incelemesi bekleniyor", phase="finalization")
    elif sonuc == "Testler kaldı":
        await gp.add_label(rp, n, "test/failed")
    else:  # Test edilemedi / kural ihlali: kosu basarisiz -> status/on-hold
        raise RuntimeError(f"Test kosusu: {sonuc}")


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


async def _post_review_comment(
    task_run: TaskRun, pr_number: int, session: AsyncSession, oto: bool = False
) -> None:
    """Post AI review results as a comment on the source PR."""
    repo_path = f"{task_run.repo_owner}/{task_run.repo_name}"
    # bimetri yamasi: incelemedeki @ yeni kosu tetiklemesin; otomatik turda yorum @agentickode ile baslar
    body = _build_review_comment(task_run.review_result).replace("@", "@​")
    # bimetri yamasi: inceleme yorumunda da ajan, model ve kosu (kod PR'i ve test raporu gibi)
    from backend.config import settings as _settings

    _cr = task_run.coding_results or {}
    body = body.removesuffix("*AgenticKode incelemesi*") + (
        f"Ajan: {_cr.get('agent') or '?'}"
        + (f" · Model: {_cr['model']}" if _cr.get("model") else "")
        + f" · Koşu: [#{task_run.id}]({_settings.app_base_url.rstrip('/')}/runs/{task_run.id})"
        + " · AgenticKode incelemesi"
    )
    if oto:
        body = OTO_YORUM.format(neden="İnceleme değişiklik istedi; aşağıdaki bulguları düzelt.") + body

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

    # bimetri yamasi: Turkce baslik; sabit Status/Issues/Suggestions satirlari yalnizca yapilandirilmis sonucta
    parts = ["## AI Kod İncelemesi\n"]

    if summary:
        parts.append(f"{summary}\n")

    if issues or suggestions:
        status = "Onaylandı" if approved else "Değişiklik gerekli"
        parts.append(f"**Durum**: {status}")
        parts.append(f"**Bulgu**: {len(issues)}")
        parts.append(f"**Öneri**: {len(suggestions)}\n")

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
    # bimetri yamasi: altbilgi
    parts.append("*AgenticKode incelemesi*")
    return "\n".join(parts)

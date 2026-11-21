# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: Gitea PR olaylari - insan push'u zinciri yeniden baslatir, insan PR'i CI'a gider."""

import contextlib
import logging
from types import SimpleNamespace
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ProjectConfig

logger = logging.getLogger("agentickode.webhooks.bimetri_push")


async def proje_saglayici(project: ProjectConfig, db: AsyncSession):
    """Projenin Gitea token'iyla GitProvider."""
    from backend.services.git import get_git_provider
    from backend.services.http_client import get_http_client
    from backend.worker.phases._helpers import get_project_token

    token = await get_project_token(
        SimpleNamespace(
            git_provider="gitea",
            project_id=project.project_id,
            workspace_server_id=getattr(project, "workspace_server_id", None),
        ),
        db,
    )
    return get_git_provider("gitea", get_http_client(), access_token=token)


async def mvnw_var_mi(gp, full: str, dal: str) -> bool:
    r = await gp._client.get(
        f"{gp._base_url}/api/v1/repos/{full}/contents/mvnw",
        params={"ref": dal},
        headers=gp._headers(),
        timeout=30.0,
    )
    return r.status_code == 200


_SALT_BIRLESME_DOSYA_SINIRI = 100


async def _api(gp, yol: str, params: dict | None = None):
    return await gp._client.get(
        f"{gp._base_url}/api/v1{yol}", params=params, headers=gp._headers(), timeout=30.0
    )


async def _blob(gp, full: str, yol: str, ref: str) -> str | None:
    """Dosyanin o ref'teki blob sha'si; dosya yoksa None. Dosya degilse (dizin vb.) hata."""
    r = await _api(gp, f"/repos/{full}/contents/{quote(yol)}", {"ref": ref})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    veri = r.json()
    if not isinstance(veri, dict) or veri.get("type") not in ("file", "symlink"):
        raise ValueError(f"dosya degil: {yol}")
    return veri.get("sha")


async def salt_hedef_birlesmesi(gp, full: str, pr: dict) -> bool:
    """PR'in son commit'i yalnizca hedef dali iceri alan bir merge mi ("Update branch").

    Kosullar: iki ebeveyn; ikinci ebeveyn hedef dalda; ilk ebeveynde zincir bitmis (ci-kapisi
    durumu var); merge commit'in ilk ebeveynden farki olan her dosya ikinci ebeveyndekiyle
    birebir ayni (ne cakisma cozumu ne elle ek degisiklik). Belirsizlikte False: test kosar."""
    from backend.worker.phases._bimetri_ci import CI_BAGLAM

    sha = (pr.get("head") or {}).get("sha") or ""
    hedef = (pr.get("base") or {}).get("ref") or ""
    if not sha or not hedef:
        return False
    try:
        r = await _api(gp, f"/repos/{full}/git/commits/{sha}", {"files": "true"})
        r.raise_for_status()
        commit = r.json()
        ebeveyn = [e.get("sha") for e in commit.get("parents") or []]
        if len(ebeveyn) != 2 or not all(ebeveyn):
            return False
        once, hedeften = ebeveyn
        r = await _api(gp, f"/repos/{full}/compare/{quote(hedef, safe='')}...{hedeften}")
        r.raise_for_status()
        if r.json().get("total_commits") != 0:
            return False  # ikinci ebeveyn hedef dalda degil
        r = await _api(gp, f"/repos/{full}/commits/{once}/status")
        r.raise_for_status()
        if not any(s.get("context") == CI_BAGLAM for s in r.json().get("statuses") or []):
            return False  # onceki commit'te zincir bitmemis
        dosyalar = commit.get("files") or []
        if len(dosyalar) >= _SALT_BIRLESME_DOSYA_SINIRI:
            return False
        for d in dosyalar:
            for yol in {d.get("filename"), d.get("previous_filename")} - {None, ""}:
                if await _blob(gp, full, yol, sha) != await _blob(gp, full, yol, hedeften):
                    return False
        return True
    except Exception:
        logger.warning("%s: salt hedef birlesmesi denetlenemedi (%s)", full, sha, exc_info=True)
        return False


async def insan_pr_ci(gp, full: str, n: int, label_names: list[str]) -> dict | None:
    """Insanin kendi PR'i: zincir yok; inceleme ya da test istenmediyse CI kapisi hemen baslar."""
    from backend.worker.phases._bimetri_ci import ci_baslat

    if "ai-review" in label_names or "ai-test" in label_names:
        return None  # once inceleme/test; CI zincirin sonunda
    sonuc = await ci_baslat(gp, full, n)
    logger.info("%s PR #%s (insan PR'i): %s", full, n, sonuc)
    return {"status": "accepted", "reason": "human_pr_ci"}


async def push_karari(gp, body: dict, label_names: list[str]) -> dict | None:
    """opened/reopened/synchronized: bot olayi -> yok say (zincir etiketlerle ilerler); insanin
    kendi PR'i -> CI; insan push'u botun PR'inda -> salt hedef dal birlesmesiyse yalniz CI,
    degilse ai-test (test gerekliyse), istenmisse inceleme, degilse CI. None: karar yok, normal akis devam etsin."""
    from backend.worker.phases._bimetri_ci import ajan_testi_gerekli, ci_baslat
    from backend.worker.phases._bimetri_oto import bot_login

    pr = body.get("pull_request") or {}
    full = body.get("repository", {}).get("full_name", "")
    n = int(pr.get("number") or 0)
    bot = await bot_login(gp)
    gonderen = (body.get("sender") or {}).get("login")
    if not bot or gonderen == bot:
        return {"status": "ignored", "reason": "bot_push"}
    if pr.get("state") != "open" or pr.get("merged"):
        return {"status": "ignored", "reason": "pr_not_open"}
    if (pr.get("user") or {}).get("login") != bot:
        return await insan_pr_ci(gp, full, n, label_names)
    if body.get("action") != "synchronized":
        return None  # botun PR'i acildi: zincir etiketlerle ilerler
    if "ai-test" in label_names or "status/on-hold" in label_names:
        return {"status": "ignored", "reason": "test_not_on_push"}
    if await salt_hedef_birlesmesi(gp, full, pr):
        if "ai-review" in label_names:
            return None  # bekleyen inceleme kosar; CI sonra
        sonuc = await ci_baslat(gp, full, n)  # kod degismedi: test/inceleme etiketleri gecerli
        logger.info("%s PR #%s: hedef dal birlesmesi (%s), %s", full, n, gonderen, sonuc)
        return {"status": "accepted", "reason": "base_merge_ci"}
    dal = (pr.get("head") or {}).get("ref", "")
    if not await ajan_testi_gerekli(gp, full, n, await mvnw_var_mi(gp, full, dal)):
        if "ai-review" in label_names:
            return None  # synchronized + ai-review -> inceleme kosusu; CI sonra
        sonuc = await ci_baslat(gp, full, n)
        logger.info("%s PR #%s: insan push'u (%s), %s", full, n, gonderen, sonuc)
        return {"status": "accepted", "reason": "human_push_ci"}
    for e in ("test/passed", "test/failed", "ai-tested"):
        with contextlib.suppress(Exception):
            await gp.remove_label(full, n, e)
    await gp.add_label(full, n, "ai-test")  # label_updated -> test kosusu
    logger.info("%s PR #%s: insan push'u (%s), ai-test kondu", full, n, gonderen)
    return {"status": "accepted", "reason": "human_push_test"}

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: Gitea PR olaylari - insan push'u zinciri yeniden baslatir, insan PR'i CI'a gider."""

import contextlib
import logging
from types import SimpleNamespace

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
    kendi PR'i -> CI; insan push'u botun PR'inda -> ai-test (test gerekliyse), istenmisse
    inceleme, degilse CI. None: karar yok, normal akis devam etsin."""
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

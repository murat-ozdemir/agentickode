# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: Gitea PR dalina push (synchronized) - insan push'u testi yeniden baslatir."""

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


async def push_karari(gp, body: dict, label_names: list[str]) -> dict | None:
    """synchronized olayi: bot push'u -> yok say (zincir etiketlerle ilerler); insan push'u
    botun PR'inda -> ai-test (mvnw varsa). None: karar yok, normal akis devam etsin."""
    from backend.worker.phases._bimetri_oto import bot_login

    pr = body.get("pull_request") or {}
    full = body.get("repository", {}).get("full_name", "")
    n = int(pr.get("number") or 0)
    bot = await bot_login(gp)
    gonderen = (body.get("sender") or {}).get("login")
    if not bot or gonderen == bot:
        return {"status": "ignored", "reason": "bot_push"}
    if (pr.get("user") or {}).get("login") != bot:
        return None  # insanin kendi PR'i: eski davranis
    if "ai-test" in label_names or "status/on-hold" in label_names:
        return {"status": "ignored", "reason": "test_not_on_push"}
    if pr.get("state") != "open" or pr.get("merged"):
        return {"status": "ignored", "reason": "pr_not_open"}
    if not await mvnw_var_mi(gp, full, (pr.get("head") or {}).get("ref", "")):
        return None
    for e in ("test/passed", "test/failed", "ai-tested"):
        with contextlib.suppress(Exception):
            await gp.remove_label(full, n, e)
    await gp.add_label(full, n, "ai-test")  # label_updated -> test kosusu
    logger.info("%s PR #%s: insan push'u (%s), ai-test kondu", full, n, gonderen)
    return {"status": "accepted", "reason": "human_push_test"}

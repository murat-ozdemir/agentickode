# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 5): an open contract question stops the auto-fix loop.

The test, review and fix agents write a question the issue leaves open under `### Açık soru`.
Guessing the answer made agents contradict each other round after round; instead the loop
stops on the agent's PR (status/on-hold on the PR and its issue) and the question is posted.
`@agentickode devam <yanıt>` starts a fix round with the answer and the chain goes on.
"""

import contextlib
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskRun
from backend.worker.phases._bimetri_etiket import issue_no_bul
from backend.worker.phases._bimetri_oto import beklet, oto_pr

logger = logging.getLogger("agentickode.phases.bimetri_soru")

SORU_BASLIGI = "### Açık soru"
_SORU_SINIRI = 3000
_BASLIK_RX = re.compile(r"(?im)^#{2,4}\s*a[çc][ıi]k\s+soru(?:lar)?\s*:?\s*$")
_SON_RX = re.compile(r"(?m)^(?:#{1,4}\s|\*\*Sonuç:\*\*)")
_BOS = {"", "-", "yok", "yok.", "_yok._", "yok (yanıtlanmış)"}


def acik_soru(rapor: str) -> str | None:
    """`### Açık soru` başlığının altındaki metin; başlık yoksa ya da boşsa None."""
    m = _BASLIK_RX.search(rapor or "")
    if not m:
        return None
    govde = rapor[m.end() :]
    son = _SON_RX.search(govde)
    soru = (govde[: son.start()] if son else govde).strip()
    return None if soru.lower() in _BOS else soru[:_SORU_SINIRI]


async def soru_sor(gp, rp: str, n: int, issue_no: int | None, soru: str) -> None:
    for hedef in (n, issue_no):
        if hedef:
            with contextlib.suppress(Exception):
                await gp.set_status_label(rp, int(hedef), "status/on-hold")
    # zero-width bosluk: ornek komut ve rapordaki @ yeni kosu tetiklemesin
    await gp.post_pr_comment(
        rp,
        n,
        "## Otomatik düzeltme durdu: açık soru\n\n"
        "Ajan, issue'nun yanıtlamadığı bir karar için yanıtını bekliyor:\n\n"
        + soru.replace("@", "@​")
        + "\n\nYanıtla: `@​agentickode devam <yanıt>`. Yanıtın bir düzeltme turuyla "
        "uygulanır, zincir sürer.",
    )


async def soru_karari(gp, rp: str, n: int, rapor: str, run_id: int | None = None) -> bool:
    """Raporda açık soru varsa ajanın PR'ında döngüyü durdurur, soruyu yazar; True döner."""
    soru = acik_soru(rapor)
    if not soru:
        return False
    try:
        pr = await oto_pr(gp, rp, n)
        if pr is None:
            return False
        await soru_sor(gp, rp, n, issue_no_bul(pr.get("body")), soru)
        beklet(run_id)
        return True
    except Exception:
        logger.warning("Acik soru icin dongu durdurulamadi (%s#%s)", rp, n, exc_info=True)
        return False


def ajan_raporu(task_run: TaskRun) -> str:
    """Ajanin son mesaji (test raporu ya da duzeltme ozeti)."""
    rapor = (task_run.coding_results or {}).get("response") or ""
    if isinstance(rapor, dict):  # CLI ajani: yalnizca son mesaj
        rapor = rapor.get("output") or ""
    return rapor if isinstance(rapor, str) else str(rapor)


async def kosu_soru_karari(task_run: TaskRun, n: int, session: AsyncSession, rapor: str) -> bool:
    """soru_karari, kosunun git saglayicisiyla (yalnizca Gitea)."""
    if task_run.git_provider != "gitea" or not acik_soru(rapor):
        return False
    from backend.services.git import get_git_provider
    from backend.services.http_client import get_http_client
    from backend.worker.phases._helpers import get_project_token

    gp = get_git_provider(
        "gitea", get_http_client(), access_token=await get_project_token(task_run, session)
    )
    rp = f"{task_run.repo_owner}/{task_run.repo_name}"
    return await soru_karari(gp, rp, n, rapor, task_run.id)

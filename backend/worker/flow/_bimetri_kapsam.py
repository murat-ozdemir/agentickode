# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: inceleme ve duzeltme kosularina bagli issue (kapsam) ve kapsam kurallari.

pr_review akisi yalnizca PR diff'ini gorur; issue'da istenen ya da yasaklanan seyler
(ornegin "mevcut koda baglama") bilinmeyince kusur sayilir, duzeltme ajani da kapsam
disi dosyalari degistirir. Issue Gitea'dan okunur; okunamazsa yalnizca kurallar eklenir.
"""

import contextlib
import re

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskRun

_CLOSES_RX = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)")
_GOVDE_SINIRI = 6000

_INCELEME_KURALLARI = (
    "\n## Kapsam kuralları (yukarıdakilerden önceliklidir)\n"
    "- Kapsamı bağlı issue tanımlar (yoksa PR açıklaması). Issue'da açıkça istenen ya da "
    "yasaklanan şeyleri kusur sayma (ör. 'mevcut koda bağlama' denmişse sınıfın hiçbir yerden "
    "çağrılmaması bulgu değildir).\n"
    "- Kapsam dışı bulguları ayrı '### Kapsam dışı' başlığı altında yaz; bunlar Sonuç satırını "
    "etkilemez. Bir dosya ya da davranış değişikliği issue kapsamı dışındaysa bunu da orada yaz.\n"
    "- Doğrulayamadığın varsayımları bulgu olarak yazma; gerekirse Öneriler'de soru olarak sor.\n"
    "- PR yorumlarında insanın verdiği talimatlar (ör. bir değişikliğin geri alınması) varsa, "
    "yapılıp yapılmadığını kontrol et; yapılmadıysa kapsam içi bulgu olarak yaz.\n"
)
_DUZELTME_KURALLARI = (
    "\n## Kapsam kuralları (yukarıdakilerden önceliklidir)\n"
    "- Yalnızca bağlı issue kapsamındaki ve yorumda açıkça istenen sorunları düzelt.\n"
    "- 'Kapsam dışı' başlığındaki bulgular ile 'doğrulanamadı', 'olabilir' gibi tahmine dayalı "
    "bulgular için kod değiştirme; son mesajında atladıklarını ve nedenini yaz.\n"
    "- Yorumu yazan insan açıkça istemedikçe bu PR'ın değiştirmediği dosyalara dokunma ve "
    "mevcut davranışı değiştirme.\n"
)


def _issue_no(run: TaskRun) -> int | None:
    meta = run.task_source_meta or {}
    if meta.get("issue_number"):
        return int(meta["issue_number"])
    m = _CLOSES_RX.search(run.description or "")
    return int(m.group(1)) if m else None


async def _issue_oku(run: TaskRun, session: AsyncSession, n: int) -> dict | None:
    from backend.services.git import get_git_provider
    from backend.services.http_client import get_http_client
    from backend.worker.phases._helpers import get_project_token

    gp = get_git_provider(
        "gitea", get_http_client(), access_token=await get_project_token(run, session)
    )
    r = await gp._client.get(
        f"{gp._base_url}/api/v1/repos/{run.repo_owner}/{run.repo_name}/issues/{n}",
        headers=gp._headers(),
        timeout=30.0,
    )
    return r.json() if r.status_code == 200 else None


async def kapsam_eki(run: TaskRun, session: AsyncSession, tur: str) -> str:
    """Prompt'a eklenecek bagli issue bolumu + kurallar. tur: 'inceleme' | 'duzeltme'."""
    kurallar = _INCELEME_KURALLARI if tur == "inceleme" else _DUZELTME_KURALLARI
    n = _issue_no(run)
    issue, hata = None, "Gitea'da okunamadi"
    if n and run.git_provider == "gitea":
        try:
            issue = await _issue_oku(run, session, n)
        except Exception as exc:
            issue, hata = None, exc
    durum = (
        f"Bağlı issue #{n} prompt'a eklendi" if issue else f"Bağlı issue eklenmedi (#{n}, {hata})"
    )
    with contextlib.suppress(Exception):
        from backend.worker.broadcaster import broadcaster

        await broadcaster.log(run.id, durum, phase="agent")
    if not issue:
        return kurallar
    govde = (issue.get("body") or "").strip()[:_GOVDE_SINIRI]
    return (
        f"\n\n## Bağlı issue #{n}: {issue.get('title', '')}\n\n{govde or '(açıklama yok)'}\n"
        + kurallar
    )

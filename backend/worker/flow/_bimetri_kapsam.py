# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: inceleme ve duzeltme kosularina bagli issue (kapsam) ve kapsam kurallari.

pr_review akisi yalnizca PR diff'ini gorur; issue'da istenen ya da yasaklanan seyler
(ornegin "mevcut koda baglama") bilinmeyince kusur sayilir, duzeltme ajani da kapsam
disi dosyalari degistirir. Issue Gitea'dan okunur; okunamazsa yalnizca kurallar eklenir.

Kapsami PR'da insanin yazdigi istekler de genisletir (ornek: "bir de .env.example ekle").
pr_fetch yalnizca resmi incelemeleri (/pulls/N/reviews) alir, PR yorumlari incelemeye
hic gitmez; bu yuzden insan yorumlari (bot ve yalniz komut olanlar haric) ayrica eklenir.
"""

import contextlib
import re

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskRun

_CLOSES_RX = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)")
_GOVDE_SINIRI = 6000
_YORUM_SINIRI = 1500
_YORUMLAR_SINIRI = 5000

_INCELEME_KURALLARI = (
    "\n## Kapsam kuralları (yukarıdakilerden önceliklidir)\n"
    "- Kapsamı bağlı issue (yoksa PR açıklaması) ve 'PR'da insanın istekleri' bölümündeki "
    "yorumlar birlikte tanımlar; PR'da hangi dosyaların değiştiği kapsamı genişletmez. Bu "
    "ikisinde açıkça istenen ya da yasaklanan şeyleri kusur sayma (ör. 'mevcut koda bağlama' "
    "denmişse sınıfın hiçbir yerden çağrılmaması bulgu değildir).\n"
    "- PR yorumunda insanın istediği dosya ya da değişiklik kapsam içidir; issue'da geçmese de "
    "onu 'Kapsam dışı değişiklik' sayma, içeriğini normal incele.\n"
    "- Issue'nun ve insan isteklerinin gerektirmediği her dosya ya da davranış değişikliği için "
    "(önceki otomatik düzeltmelerin yaptıkları dahil) tek bulgu yaz: '**kritik** — Kapsam dışı "
    "değişiklik: <dosya> hedef daldaki hâline döndürülmeli'. Bu bulgu Sonuç'u 'Değişiklik "
    "gerekli' yapar. O dosyanın içeriği hakkında başka bulgu ya da öneri yazma.\n"
    "- Kapsam içi koda dair olmayan diğer gözlemleri ayrı '### Kapsam dışı' başlığı altında yaz; "
    "bunlar Sonuç satırını etkilemez.\n"
    "- Doğrulayamadığın varsayımları bulgu olarak yazma; gerekirse Öneriler'de soru olarak sor.\n"
    "- İnsanın PR yorumundaki talimatlar (ör. bir dosya eklenmesi ya da bir değişikliğin geri "
    "alınması) yapılmadıysa ya da sonradan geri alındıysa kapsam içi bulgu olarak yaz.\n"
)
_DUZELTME_KURALLARI = (
    "\n## Kapsam kuralları (yukarıdakilerden önceliklidir)\n"
    "- Yalnızca bağlı issue kapsamındaki ve insanın PR yorumlarında açıkça istediği sorunları "
    "düzelt.\n"
    "- 'Kapsam dışı değişiklik' bulgusunda dosyayı yalnızca hedef daldaki hâline döndür: "
    "`git checkout origin/{base} -- <dosya>` (hedef dalda yoksa `git rm <dosya>`). O dosyada "
    "başka değişiklik yapma, iyileştirme deneme.\n"
    "- Bulgu bir dosyayı kapsam dışı saysa da o dosyayı ya da değişikliği 'PR'da insanın "
    "istekleri' bölümünde bir insan istemişse geri alma; son mesajında bunu nedeniyle yaz.\n"
    "- '### Kapsam dışı' başlığındaki bulgular ile 'doğrulanamadı', 'olabilir' gibi tahmine "
    "dayalı bulgular için kod değiştirme; son mesajında atladıklarını ve nedenini yaz.\n"
    "- Yorumu yazan insan açıkça istemedikçe issue'nun gerektirmediği dosyalara dokunma ve "
    "mevcut davranışı değiştirme (yukarıdaki geri alma dışında).\n"
)
_TEST_KURALLARI = (
    "\n## Kapsam kuralları (yukarıdakilerden önceliklidir)\n"
    "- Beklenen davranışı bağlı issue ve 'PR'da insanın istekleri' bölümü tanımlar; testleri "
    "koda göre değil bunlara göre yaz.\n"
    "- Kod issue ile çelişiyorsa testi issue'ya göre yaz, kalmasına izin ver ve raporla.\n"
    "- PR'daki mevcut bir testin beklediği değer issue ile çelişiyorsa testi issue'ya göre "
    "güncelle (yalnızca `src/test/**`); raporda hangi testi neden değiştirdiğini yaz.\n"
    "- Issue ilgili kuralı açıkça tanımlamıyorsa hiçbir testi değiştirme; raporda "
    "'Açık soru' olarak yaz.\n"
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


async def _pr_yorumlari(run: TaskRun, session: AsyncSession, n: int) -> tuple[list, str]:
    """PR'in (issue) yorumlari ve botun login'i."""
    from backend.services.git import get_git_provider
    from backend.services.http_client import get_http_client
    from backend.worker.phases._bimetri_oto import bot_login
    from backend.worker.phases._helpers import get_project_token

    gp = get_git_provider(
        "gitea", get_http_client(), access_token=await get_project_token(run, session)
    )
    r = await gp._client.get(
        f"{gp._base_url}/api/v1/repos/{run.repo_owner}/{run.repo_name}/issues/{n}/comments",
        headers=gp._headers(),
        params={"limit": 50},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json(), await bot_login(gp)


def _insan_istekleri(yorumlar: list, bot: str) -> str:
    """Botun olmayan ve yalniz komut (review/tekrar/devam) olmayan yorumlar, eskiden yeniye."""
    from backend.api._bimetri_komut import komut_ayikla

    satirlar, toplam = [], 0
    for c in yorumlar:
        login = (c.get("user") or {}).get("login", "")
        govde = (c.get("body") or "").strip()
        komut, kalan = komut_ayikla(govde)
        if not govde or login == bot or (komut != "duzelt" and not kalan):
            continue
        if len(govde) > _YORUM_SINIRI:
            govde = govde[:_YORUM_SINIRI] + " [...]"
        satir = f"- {login} ({(c.get('created_at') or '')[:16]}): {govde}"
        if toplam + len(satir) > _YORUMLAR_SINIRI:
            break
        satirlar.append(satir)
        toplam += len(satir)
    return "\n".join(satirlar)


async def _istekler_eki(run: TaskRun, session: AsyncSession) -> str:
    pr = (run.task_source_meta or {}).get("pr_number")
    if not pr or run.git_provider != "gitea":
        return ""
    try:
        metin = _insan_istekleri(*await _pr_yorumlari(run, session, int(pr)))
    except Exception:
        return ""
    if not metin:
        return ""
    return f"\n\n## PR'da insanın istekleri (PR #{pr} yorumları; kapsamın parçası)\n\n{metin}\n"


async def kapsam_eki(run: TaskRun, session: AsyncSession, tur: str) -> str:
    """Prompt'a eklenecek bagli issue bolumu + kurallar. tur: 'inceleme' | 'test' | 'duzeltme'."""
    if tur == "inceleme":
        kurallar = _INCELEME_KURALLARI
    elif tur == "test":
        kurallar = _TEST_KURALLARI
    else:
        kurallar = _DUZELTME_KURALLARI.replace("{base}", run.default_branch or "main")
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
    istekler = await _istekler_eki(run, session)
    if not issue:
        return istekler + kurallar
    govde = (issue.get("body") or "").strip()[:_GOVDE_SINIRI]
    return (
        f"\n\n## Bağlı issue #{n}: {issue.get('title', '')}\n\n{govde or '(açıklama yok)'}\n"
        + istekler
        + kurallar
    )

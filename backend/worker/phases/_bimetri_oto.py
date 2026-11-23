# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: otomatik duzeltme turlari - en fazla 3 tur; 2 turdan sonra zorluk artacaksa
donguyu durdurup sorar (_bimetri_yukselt)."""

import contextlib
import logging

from backend.worker.phases._bimetri_etiket import issue_no_bul
from backend.worker.phases._bimetri_yukselt import sonraki_zorluk, yukseltme_sor

logger = logging.getLogger("agentickode.phases.bimetri_oto")

OTO_ISARET = "<!-- agentickode-oto -->"
DEVAM_ISARET = "<!-- agentickode-devam -->"
OTO_TUR_SINIRI = 3

# Bu yorumu webhook (gitea-pr-comment) duzeltme kosusuna cevirir
OTO_YORUM = (
    "@agentickode {neden} Uygulama kodunu düzelt; test ajanının testlerini değiştirme, "
    "bir test yanlışsa son mesajında açıkla.\n" + OTO_ISARET + "\n\n"
)

# Sinira takilan kosu: executor sonda status/review koymasin (on-hold kalsin)
_BEKLETILEN: set[int] = set()


def bekletildi_mi(run_id: int) -> bool:
    if run_id in _BEKLETILEN:
        _BEKLETILEN.discard(run_id)
        return True
    return False


async def bot_login(gp) -> str:
    r = await gp._client.get(f"{gp._base_url}/api/v1/user", headers=gp._headers(), timeout=30.0)
    r.raise_for_status()
    return r.json().get("login") or ""


async def oto_tur_sayisi(gp, rp: str, n: int) -> int:
    """Son "devam" isaretinden bu yana botun actigi otomatik tur sayisi."""
    r = await gp._client.get(
        f"{gp._base_url}/api/v1/repos/{rp}/issues/{n}/comments", headers=gp._headers(), timeout=30.0
    )
    r.raise_for_status()
    sayi = 0
    for c in r.json():
        govde = c.get("body") or ""
        if DEVAM_ISARET in govde:
            sayi = 0
        elif OTO_ISARET in govde:
            sayi += 1
    return sayi


async def beklemeye_al(gp, rp: str, n: int, issue_no: int | None) -> None:
    """PR'a ve bagli issue'ya status/on-hold."""
    for hedef in (n, issue_no):
        if hedef:
            with contextlib.suppress(Exception):
                await gp.set_status_label(rp, int(hedef), "status/on-hold")


async def _sinir_doldu(gp, rp: str, n: int, issue_no: int | None, neden: str) -> None:
    # zero-width bosluk: ornek komutlar botun kendi yorumu olarak yeniden komut sayilmasin
    await beklemeye_al(gp, rp, n, issue_no)
    await gp.post_pr_comment(
        rp,
        n,
        f"## Otomatik düzeltme durdu: {OTO_TUR_SINIRI} tur doldu\n\n"
        f"Son durum: {neden}\n\n"
        "Geri bildirimin gerekiyor. Seçenekler:\n"
        "- `@\u200bagentickode devam <yönlendirme>`: sayaç sıfırlanır, yönlendirmenle "
        f"{OTO_TUR_SINIRI} tur daha denenir.\n"
        "- `@\u200bagentickode <talimat>`: tek bir düzeltme turu.\n"
        "- Kodu kendin düzeltip PR dalına push et (test kendiliğinden başlar).\n"
        "- Issue yanlışsa PR'ı kapatıp issue'yu netleştir.",
    )


async def oto_pr(gp, rp: str, n: int) -> dict | None:
    """Otomatik dongunun surdugu PR: acik, botun actigi, status/on-hold olmayan. Degilse None."""
    r = await gp._client.get(
        f"{gp._base_url}/api/v1/repos/{rp}/pulls/{n}", headers=gp._headers(), timeout=30.0
    )
    r.raise_for_status()
    pr = r.json()
    if pr.get("state") != "open" or pr.get("merged"):
        return None
    if any(la.get("name") == "status/on-hold" for la in pr.get("labels") or []):
        return None
    bot = await bot_login(gp)
    if not bot or (pr.get("user") or {}).get("login") != bot:
        return None
    return pr


def beklet(run_id: int | None) -> None:
    """Kosu sonunda executor status/review koymasin; PR ve issue status/on-hold kalsin."""
    if run_id is not None:
        _BEKLETILEN.add(run_id)


async def oto_tur_karari(gp, rp: str, n: int, neden: str, run_id: int | None = None) -> bool:
    """Otomatik duzeltme turu acilsin mi. Yalnizca acik, botun actigi, status/on-hold olmayan PR'da;
    sinir dolduysa PR ve issue status/on-hold olur ve insandan geri bildirim istenir."""
    try:
        pr = await oto_pr(gp, rp, n)
        if pr is None:
            return False
        issue_no = issue_no_bul(pr.get("body"))
        sayi = await oto_tur_sayisi(gp, rp, n)
        if sayi >= OTO_TUR_SINIRI:
            await _sinir_doldu(gp, rp, n, issue_no, neden)
            beklet(run_id)
            return False
        # bimetri (dongu verimliligi 6. madde): daha guclu modele gecmeden once sor
        sonraki = await sonraki_zorluk(gp, rp, n, issue_no) if sayi == OTO_TUR_SINIRI - 1 else None
        if sonraki:
            await beklemeye_al(gp, rp, n, issue_no)
            await yukseltme_sor(gp, rp, n, sonraki[1], sonraki[2], neden)
            beklet(run_id)
            return False
        return True
    except Exception:
        logger.warning("Otomatik tur karari verilemedi (%s#%s)", rp, n, exc_info=True)
        return False

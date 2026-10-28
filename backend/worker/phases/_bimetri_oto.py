# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: otomatik duzeltme turlari - en fazla 3 tur, 3. turda zorluk bir kademe artar."""

import contextlib
import logging

from backend.worker.phases._bimetri_etiket import ZORLUKLAR, etiketler, grup_degeri, issue_no_bul

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


async def zorluk_artir(gp, rp: str, n: int, issue_no: int | None) -> str | None:
    """PR'in zorlugunu bir kademe artirir. Insan PR'da zorlugu degistirdiyse (issue'dakinden
    farkli) ya da zaten en ustteyse dokunmaz. Yeni zorlugu dondurur."""
    pr_z = grup_degeri(await etiketler(gp, rp, n), "difficulty/")
    issue_z = grup_degeri(await etiketler(gp, rp, issue_no), "difficulty/")
    if pr_z and pr_z != issue_z:
        return None
    eski = pr_z or issue_z or "easy"
    if eski not in ZORLUKLAR or eski == ZORLUKLAR[-1]:
        return None
    yeni = ZORLUKLAR[ZORLUKLAR.index(eski) + 1]
    if pr_z:
        await gp.remove_label(rp, n, f"difficulty/{pr_z}")
    await gp.add_label(rp, n, f"difficulty/{yeni}")
    await gp.post_pr_comment(
        rp,
        n,
        f"{OTO_TUR_SINIRI - 1} otomatik tur sorunu çözmedi; son tur için zorluk "
        f"`difficulty/{eski}` → `difficulty/{yeni}` yükseltildi (daha güçlü model).",
    )
    return yeni


async def _sinir_doldu(gp, rp: str, n: int, issue_no: int | None, neden: str) -> None:
    for hedef in (n, issue_no):
        if hedef:
            with contextlib.suppress(Exception):
                await gp.set_status_label(rp, int(hedef), "status/on-hold")
    await gp.post_pr_comment(
        rp,
        n,
        f"## Otomatik düzeltme durdu: {OTO_TUR_SINIRI} tur doldu\n\n"
        f"Son durum: {neden}\n\n"
        "Geri bildirimin gerekiyor. Seçenekler:\n"
        "- `@agentickode devam <yönlendirme>`: sayaç sıfırlanır, yönlendirmenle "
        f"{OTO_TUR_SINIRI} tur daha denenir.\n"
        "- `@agentickode <talimat>`: tek bir düzeltme turu.\n"
        "- Kodu kendin düzeltip PR dalına push et (test kendiliğinden başlar).\n"
        "- Issue yanlışsa PR'ı kapatıp issue'yu netleştir.",
    )


async def oto_tur_karari(gp, rp: str, n: int, neden: str, run_id: int | None = None) -> bool:
    """Otomatik duzeltme turu acilsin mi. Yalnizca acik, botun actigi, status/on-hold olmayan PR'da;
    sinir dolduysa PR ve issue status/on-hold olur ve insandan geri bildirim istenir."""
    try:
        r = await gp._client.get(
            f"{gp._base_url}/api/v1/repos/{rp}/pulls/{n}", headers=gp._headers(), timeout=30.0
        )
        r.raise_for_status()
        pr = r.json()
        if pr.get("state") != "open" or pr.get("merged"):
            return False
        if any(la.get("name") == "status/on-hold" for la in pr.get("labels") or []):
            return False
        bot = await bot_login(gp)
        if not bot or (pr.get("user") or {}).get("login") != bot:
            return False
        issue_no = issue_no_bul(pr.get("body"))
        sayi = await oto_tur_sayisi(gp, rp, n)
        if sayi >= OTO_TUR_SINIRI:
            await _sinir_doldu(gp, rp, n, issue_no, neden)
            if run_id is not None:
                _BEKLETILEN.add(run_id)
            return False
        if sayi == OTO_TUR_SINIRI - 1:
            with contextlib.suppress(Exception):
                await zorluk_artir(gp, rp, n, issue_no)
        return True
    except Exception:
        logger.warning("Otomatik tur karari verilemedi (%s#%s)", rp, n, exc_info=True)
        return False

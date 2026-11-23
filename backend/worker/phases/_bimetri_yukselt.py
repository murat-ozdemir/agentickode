# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 6): raising the difficulty stops and asks first.

After two failed auto-fix rounds the next round would run on a stronger (costlier) model.
The loop no longer raises on its own: it stops (status/on-hold) and asks with a marked
comment. `@agentickode devam` applies the pending raise, then resets the round counter.
A difficulty the human changed on the PR in between wins; the raise is skipped.
"""

import re

from backend.worker.phases._bimetri_etiket import ZORLUKLAR, etiketler, grup_degeri

_ISARET = "<!-- agentickode-yukselt:{eski}:{yeni} -->"
_ISARET_RX = re.compile(r"<!-- agentickode-yukselt:([a-z]+):([a-z]+) -->")


async def sonraki_zorluk(gp, rp: str, n: int, issue_no: int | None) -> tuple | None:
    """(PR'daki zorluk, eski, yeni). Insan PR'da zorlugu degistirdiyse (issue'dakinden farkli)
    ya da zaten en ustteyse None."""
    pr_z = grup_degeri(await etiketler(gp, rp, n), "difficulty/")
    issue_z = grup_degeri(await etiketler(gp, rp, issue_no), "difficulty/")
    if pr_z and pr_z != issue_z:
        return None
    eski = pr_z or issue_z or "easy"
    if eski not in ZORLUKLAR or eski == ZORLUKLAR[-1]:
        return None
    return pr_z, eski, ZORLUKLAR[ZORLUKLAR.index(eski) + 1]


async def yukseltme_sor(gp, rp: str, n: int, eski: str, yeni: str, neden: str) -> None:
    from backend.worker.phases._bimetri_oto import OTO_TUR_SINIRI

    # zero-width bosluk: ornek komutlar botun kendi yorumu olarak yeniden komut sayilmasin
    await gp.post_pr_comment(
        rp,
        n,
        "## Otomatik düzeltme durdu: zorluk yükseltilsin mi?\n\n"
        f"{OTO_TUR_SINIRI - 1} otomatik tur sorunu çözmedi. Son durum: {neden}\n\n"
        f"Sıradaki tur daha güçlü ve daha pahalı bir modelle çalışır: `difficulty/{eski}` → "
        f"`difficulty/{yeni}`. Seçenekler:\n"
        "- `@​agentickode devam [yönlendirme]`: zorluk yükseltilir, sayaç sıfırlanır, "
        f"{OTO_TUR_SINIRI} tur daha denenir.\n"
        "- `@​agentickode <talimat>`: aynı zorlukta tek bir düzeltme turu.\n"
        "- Kodu kendin düzeltip PR dalına push et (test kendiliğinden başlar).\n"
        "- Issue yanlışsa PR'ı kapatıp issue'yu netleştir.\n"
        + _ISARET.format(eski=eski, yeni=yeni),
    )


async def _bekleyen(gp, rp: str, n: int) -> tuple | None:
    """Son "devam"dan sonra sorulmus, uygulanmamis yukseltme: (eski, yeni)."""
    from backend.worker.phases._bimetri_oto import DEVAM_ISARET

    r = await gp._client.get(
        f"{gp._base_url}/api/v1/repos/{rp}/issues/{n}/comments", headers=gp._headers(), timeout=30.0
    )
    r.raise_for_status()
    bekleyen = None
    for c in r.json():
        govde = c.get("body") or ""
        if DEVAM_ISARET in govde:
            bekleyen = None
        elif m := _ISARET_RX.search(govde):
            bekleyen = (m.group(1), m.group(2))
    return bekleyen


async def bekleyen_yukseltme(gp, rp: str, n: int, issue_no: int | None) -> str | None:
    """`devam`da sorulmus yukseltmeyi uygular; yeni zorlugu dondurur. Zorluk arada
    degistiyse (insan etiketi degistirdi) uygulamaz."""
    bekleyen = await _bekleyen(gp, rp, n)
    simdi = await sonraki_zorluk(gp, rp, n, issue_no) if bekleyen else None
    if not simdi or simdi[1:] != bekleyen:
        return None
    pr_z, _eski, yeni = simdi
    if pr_z:
        await gp.remove_label(rp, n, f"difficulty/{pr_z}")
    await gp.add_label(rp, n, f"difficulty/{yeni}")
    return yeni

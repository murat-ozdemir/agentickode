# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: `@agentickode <komut>` yorumlari - yetki denetimi ve review/devam komutlari."""

import contextlib
import re

_KOMUTLAR = {
    "review": "review",
    "inceleme": "review",
    "incele": "review",
    "tekrar": "tekrar",
    "retry": "tekrar",
    "devam": "devam",
    "continue": "devam",
}
_MENTION_RX = re.compile(r"(?i)@(?:agentickode|ai-agent|autofix)\b")
_YAZMA = ("write", "admin", "owner")

DEVAM_VARSAYILAN = (
    "Otomatik düzeltmeye devam et: son test raporundaki ve inceleme yorumlarındaki sorunları "
    "uygulama kodunda düzelt; test ajanının testlerini değiştirme."
)


def komut_ayikla(govde: str) -> tuple[str, str]:
    """('review'|'tekrar'|'devam'|'duzelt', kalan talimat). Komut, mention'dan hemen sonraki ilk kelime."""
    m = _MENTION_RX.search(govde or "")
    if not m:
        return "duzelt", (govde or "").strip()
    once, sonra = govde[: m.start()], govde[m.end() :]
    kelimeler = sonra.strip().split(maxsplit=1)
    ilk = kelimeler[0].strip(".,:;!?").lower() if kelimeler else ""
    if ilk in _KOMUTLAR:
        kalan = (once + " " + (kelimeler[1] if len(kelimeler) > 1 else "")).strip()
        return _KOMUTLAR[ilk], _MENTION_RX.sub("", kalan).strip()
    return "duzelt", _MENTION_RX.sub("", govde).strip()


async def yazma_yetkisi(gp, full: str, login: str | None) -> bool:
    """Bot ya da repoda yazma yetkisi olan / org uyesi. Izin uc noktasi bot token'ina 403
    verebilir; o zaman ortak calisan ve org uyeligine bakilir."""
    from backend.worker.phases._bimetri_oto import bot_login

    if not login:
        return False
    if login == await bot_login(gp):
        return True
    api = f"{gp._base_url}/api/v1"

    async def _get(yol: str):
        return await gp._client.get(f"{api}/{yol}", headers=gp._headers(), timeout=30.0)

    r = await _get(f"repos/{full}/collaborators/{login}/permission")
    if r.status_code == 200:
        return (r.json().get("permission") or "") in _YAZMA
    if (await _get(f"repos/{full}/collaborators/{login}")).status_code == 204:
        return True
    return (await _get(f"orgs/{full.split('/', 1)[0]}/members/{login}")).status_code == 204


async def inceleme_komutu(gp, full: str, n: int, issue_no: int | None, labels: list[str]) -> str:
    """PR'a ai-review (yeniden) konur; issue'ya da kalici olarak ai-review. on-hold ise
    PR ve issue status/review olur."""
    from backend.worker.phases._bimetri_etiket import inceleme_baslat

    if "status/on-hold" in labels:
        for hedef in (n, issue_no):
            if hedef:
                with contextlib.suppress(Exception):
                    await gp.set_status_label(full, int(hedef), "status/review")
    if issue_no:
        with contextlib.suppress(Exception):
            await gp.add_label(full, int(issue_no), "ai-review")
    await inceleme_baslat(gp, full, n)
    if "ai-test" in labels:
        return "AI incelemesi istendi; test bitince başlayacak."
    return "AI incelemesi başlatıldı."


async def devam_isareti(gp, full: str, n: int, login: str) -> None:
    """Otomatik tur sayacini sifirlar (yorumda ham @ yok: yeni kosu acmaz)."""
    from backend.worker.phases._bimetri_oto import DEVAM_ISARET, OTO_TUR_SINIRI

    await gp.post_pr_comment(
        full,
        n,
        f"{login} devam dedi: otomatik tur sayacı sıfırlandı "
        f"(en fazla {OTO_TUR_SINIRI} tur daha).\n{DEVAM_ISARET}",
    )

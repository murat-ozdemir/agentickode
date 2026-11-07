# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: basarisiz kosunun nedeni - kullanim limiti tanima ve issue/PR'a yorum.

Limit dolunca CLI hata koduyla cikar; neden yalnizca kosu logunda kaliyordu. Hata mesaji
"Kullanim limiti doldu (...)" olur ve her basarisiz kosu nedenini issue'ya ya da PR'a yazar
(kendi yorumunu zaten yazan duzeltme/test hatalari haric).
"""

import json
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

LIMIT_ONEK = "Kullanım limiti doldu"
# Claude: "You've hit your limit · resets 3pm (Europe/Istanbul)", eski bicim
# "Claude AI usage limit reached|1762430400"; Codex: "You've hit your usage limit ... try again at 3:05 PM"
_LIMIT_RX = re.compile(
    r"(?i)(hit your (usage )?limit|usage limit reached|limit reached|rate limit exceeded|"
    r"quota exceeded|insufficient_quota)"
)
_SIFIRLANMA_RX = re.compile(r"(?i)(?:resets|try again (?:at|in))\s+([^\"\\\n.]{1,60})")
_EPOCH_RX = re.compile(r"limit reached\|(\d{10})")
# Bu hatalar kendi yorumunu zaten yaziyor (duzeltme/test sonucu)
_YORUMLU = ("Duzeltme kosusu:", "Duzeltme test dosyalarina", "Test kosusu:")


def _metin(rd: dict) -> str:
    out = rd.get("output")
    out = out if isinstance(out, str) else json.dumps(out, default=str, ensure_ascii=False)
    return f"{out}\n{rd.get('stderr') or ''}"


def limit_nedeni(ajan: str, rd: dict | None) -> str | None:
    """CLI ciktisinda kullanim limiti varsa okunur neden; yoksa None."""
    metin = _metin(rd or {})
    if not _LIMIT_RX.search(metin):
        return None
    sifirlanma = ""
    if m := _EPOCH_RX.search(metin):
        an = datetime.fromtimestamp(int(m.group(1)), UTC).astimezone(ZoneInfo("Europe/Istanbul"))
        sifirlanma = an.strftime("%d.%m %H:%M")
    elif m := _SIFIRLANMA_RX.search(metin):
        sifirlanma = m.group(1).strip()
    return f"{LIMIT_ONEK} ({ajan or 'ajan'}" + (
        f", sıfırlanma: {sifirlanma})" if sifirlanma else ")"
    )


def yorum_gerekli(hata: str) -> bool:
    return not hata.startswith(_YORUMLU)


def hata_yorumu(run_id: int, kosu_url: str, hata: str) -> str:
    """Basarisiz kosu yorumu; zero-width bosluk: ornek komut botun yorumunda komut sayilmasin."""
    komut = "`@\u200bagentickode tekrar`"
    sonra = (
        f"Limit sıfırlanınca {komut} yaz; koşu kaldığı yerden değil, baştan başlar."
        if hata.startswith(LIMIT_ONEK)
        else f"Nedeni giderdikten sonra {komut} ile yeniden başlatabilirsin."
    )
    neden = hata[:1500].replace("@", "@\u200b")
    return f"## Koşu durdu: [#{run_id}]({kosu_url})\n\nNeden: {neden}\n\n{sonra}"


async def hata_bildir(run, session, hata: str) -> None:
    """Nedeni PR'a (yoksa issue'ya) yorum olarak yazar; yazamazsa kosu loguna uyari."""
    from backend.config import settings
    from backend.services.git import get_git_provider
    from backend.services.http_client import get_http_client
    from backend.worker.broadcaster import broadcaster
    from backend.worker.phases._helpers import get_project_token

    meta = run.task_source_meta or {}
    m = re.search(r"/pulls/(\d+)", run.pr_url or meta.get("pr_url") or "")
    hedef = meta.get("pr_number") or (m.group(1) if m else None) or meta.get("issue_number")
    if run.git_provider != "gitea" or not hedef or not yorum_gerekli(hata):
        return
    try:
        gp = get_git_provider(
            "gitea", get_http_client(), access_token=await get_project_token(run, session)
        )
        kosu = f"{settings.app_base_url.rstrip('/')}/runs/{run.id}"
        await gp.post_pr_comment(
            f"{run.repo_owner}/{run.repo_name}", int(hedef), hata_yorumu(run.id, kosu, hata)
        )
    except Exception as exc:
        await broadcaster.log(
            run.id, f"Hata yorumu yazilamadi: {exc}", level="warning", phase="agent"
        )

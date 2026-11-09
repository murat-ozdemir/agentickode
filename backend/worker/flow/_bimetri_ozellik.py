# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: merge edilen PR icin mem0'a 'ozellik_gecmisi' kaydi.

Metin, scripts/bimetri/mem0-bootstrap.py ile ayni bicimdedir: baslik, en yeni 5 commit konusu,
en cok degisen 5 klasor. Kayit infer=False ile yazilir (LLM yok, tek embedding). PR'in kaydi
zaten varsa yazilmaz. MEM0_URL ya da MEM0_API_KEY bossa hicbir sey yapmaz. Webhook yanitini
geciktirmemek icin arka planda calisir; hata yalnizca loglanir.
"""

import asyncio
import logging
from collections import Counter
from datetime import UTC, datetime
from pathlib import PurePosixPath

from backend.config import settings
from backend.services.http_client import get_http_client

logger = logging.getLogger("agentickode.bimetri.ozellik")

_KAYNAK = "merge"
_TUR = "ozellik_gecmisi"
_gorevler: set[asyncio.Task] = set()


def ozellik_metni(no: int, tarih: str, baslik: str, commitler: list[str], yerler: list[str]) -> str:
    metin = f"PR #{no} ({tarih}): {baslik}."
    if commitler:
        metin += " Commit'ler: " + "; ".join(commitler) + "."
    if yerler:
        metin += " Değişen yerler: " + ", ".join(yerler) + "."
    return metin[:800]


def en_yeni_konular(commitler: list[dict], sinir: int = 5) -> list[str]:
    """Gitea PR commit listesinden en yeni `sinir` commit'in konu satiri."""

    def zaman(c: dict) -> str:
        return c.get("created") or ((c.get("commit") or {}).get("committer") or {}).get("date", "")

    konular = []
    for c in sorted(commitler, key=zaman, reverse=True)[:sinir]:
        mesaj = ((c.get("commit") or {}).get("message") or "").strip()
        if mesaj:
            konular.append(mesaj.splitlines()[0])
    return konular


def degisen_yerler(dosyalar: list[dict], sinir: int = 5) -> list[str]:
    klasorler = Counter(
        str(PurePosixPath(d["filename"]).parent) for d in dosyalar if d.get("filename")
    )
    return [k for k, _ in klasorler.most_common(sinir)]


async def _gitea_listesi(provider, yol: str, params: dict) -> list[dict]:
    # GiteaProvider'da PR commit/dosya listesi yok; upstream dosyasini buyutmemek icin burada.
    r = await provider._client.get(
        f"{provider._base_url}/api/v1/repos/{yol}",
        headers=provider._headers(),
        params=params,
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json() or []


def _mem0(yol: str) -> str:
    return f"{settings.mem0_url.rstrip('/')}{yol}"


async def _pr_kaydi_var(proje: str, no: int) -> bool:
    r = await get_http_client().get(
        _mem0("/memories"),
        headers={"X-API-Key": settings.mem0_api_key},
        params={"user_id": proje, "top_k": 1000},
        timeout=15.0,
    )
    r.raise_for_status()
    govde = r.json()
    kayitlar = govde.get("results", []) if isinstance(govde, dict) else govde
    return any(
        (k.get("metadata") or {}).get("tur") == _TUR
        and str((k.get("metadata") or {}).get("pr")) == str(no)
        for k in kayitlar
    )


async def ozellik_yaz(provider, proje: str, repo_yolu: str, pr: dict) -> str:
    """'kapali', 'var' ya da 'yazildi' doner; hata firlatabilir."""
    if not (settings.mem0_url and settings.mem0_api_key):
        return "kapali"
    no = int(pr["number"])
    if await _pr_kaydi_var(proje, no):
        return "var"
    commitler = await _gitea_listesi(
        provider,
        f"{repo_yolu}/pulls/{no}/commits",
        {"limit": 50, "files": "false", "verification": "false"},
    )
    dosyalar = await _gitea_listesi(provider, f"{repo_yolu}/pulls/{no}/files", {"limit": 100})
    tarih = (pr.get("merged_at") or datetime.now(UTC).isoformat())[:10]
    metin = ozellik_metni(
        no,
        tarih,
        (pr.get("title") or "").strip(),
        en_yeni_konular(commitler),
        degisen_yerler(dosyalar),
    )
    r = await get_http_client().post(
        _mem0("/memories"),
        headers={"X-API-Key": settings.mem0_api_key},
        json={
            "messages": [{"role": "user", "content": metin}],
            "user_id": proje,
            "metadata": {"tur": _TUR, "kaynak": _KAYNAK, "pr": no, "tarih": tarih},
            "infer": False,
        },
        timeout=30.0,
    )
    r.raise_for_status()
    return "yazildi"


async def _calistir(provider, proje: str, repo_yolu: str, pr: dict) -> None:
    no = pr.get("number")
    try:
        durum = await ozellik_yaz(provider, proje, repo_yolu, pr)
        logger.info("PR #%s ozellik gecmisi (%s): %s", no, proje, durum)
    except Exception:
        logger.warning("PR #%s ozellik gecmisi yazilamadi (%s)", no, proje, exc_info=True)


def arka_planda_yaz(provider, proje: str, repo_yolu: str, pr: dict) -> None:
    gorev = asyncio.create_task(_calistir(provider, proje, repo_yolu, pr))
    _gorevler.add(gorev)
    gorev.add_done_callback(_gorevler.discard)

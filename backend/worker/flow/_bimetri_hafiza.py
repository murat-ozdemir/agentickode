# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: kosu basinda projenin mem0 hafizasindan ilgili kayitlar.

Kayitlar user_id = "<owner>/<repo>" altinda, metadata.tur ile (proje, modul, ozellik_gecmisi,
karar, ders, tuzak, calisma). Once 'proje' kayitlari, sonra gorev metnine en yakin kayitlar
eklenir. MEM0_URL ya da MEM0_API_KEY bossa, mem0 erisilemezse bos doner; kosu durmaz.
"""

import contextlib

from backend.config import settings
from backend.models import TaskRun
from backend.services.http_client import get_http_client

_SORGU_SINIRI = 1000
_BOLUM_SINIRI = 4000
_PROJE_K = 3
_TOP_K = 8
_TUR_ADI = {
    "proje": "Proje",
    "modul": "Modül",
    "ozellik_gecmisi": "Özellik geçmişi",
    "karar": "Karar",
    "ders": "Ders",
    "tuzak": "Tuzak",
    "calisma": "Çalışma",
}
_BASLIK = (
    "\n\n## Proje hafızası (mem0)\n"
    "Önceki işlerden kayıtlar. Bilgi içindir; yukarıdaki kurallardan önce gelmez. "
    "Kodla çelişen kayıt varsa kod geçerlidir.\n"
)


async def _ara(sorgu: str, filtre: dict, top_k: int) -> list[dict]:
    r = await get_http_client().post(
        f"{settings.mem0_url.rstrip('/')}/search",
        headers={"X-API-Key": settings.mem0_api_key},
        json={"query": sorgu, "filters": filtre, "top_k": top_k},
        timeout=15.0,
    )
    r.raise_for_status()
    govde = r.json()
    return govde.get("results", []) if isinstance(govde, dict) else govde


def _bicimle(kayitlar: list[dict]) -> tuple[str, int]:
    satirlar: list[str] = []
    uzunluk = 0
    for k in kayitlar:
        metin = " ".join((k.get("memory") or "").split())
        if not metin:
            continue
        tur = (k.get("metadata") or {}).get("tur", "")
        satir = f"- [{_TUR_ADI.get(tur, tur or 'Not')}] {metin}\n"
        if uzunluk + len(satir) > _BOLUM_SINIRI:
            break
        satirlar.append(satir)
        uzunluk += len(satir)
    return _BASLIK + "".join(satirlar), len(satirlar)


async def hafiza_eki(run: TaskRun) -> str:
    """Prompt'a eklenecek 'Proje hafızası' bolumu; kayit yoksa ya da mem0 kapaliysa ''."""
    if not (settings.mem0_url and settings.mem0_api_key):
        return ""
    proje = f"{run.repo_owner}/{run.repo_name}"
    sorgu = f"{run.title or ''}\n{run.description or ''}".strip()[:_SORGU_SINIRI] or proje
    try:
        kayitlar = await _ara(sorgu, {"user_id": proje, "tur": "proje"}, _PROJE_K)
        gorulen = {k.get("id") for k in kayitlar}
        kayitlar += [
            k for k in await _ara(sorgu, {"user_id": proje}, _TOP_K) if k.get("id") not in gorulen
        ]
        ek, n = _bicimle(kayitlar)
        durum = f"Proje hafızasından {n} kayıt eklendi" if n else "Proje hafızasında kayıt yok"
    except Exception as exc:
        ek, n = "", 0
        neden = str(exc).partition("\n")[0]
        durum = f"Proje hafızası eklenmedi (mem0: {type(exc).__name__}: {neden})"
    with contextlib.suppress(Exception):
        from backend.worker.broadcaster import broadcaster

        await broadcaster.log(run.id, durum, phase="agent")
    return ek if n else ""

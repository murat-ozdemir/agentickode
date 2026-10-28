# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: duzeltme kosusunun PR yorumu (ajanin son mesaji + ajan/model/kosu altbilgisi)."""

from backend.models import TaskRun

DEGISIKLIK_YOK_NOTU = (
    "\n\nZincir durdu (`status/on-hold`). Ajanın gerekçesi doğruysa gereğini yapıp "
    "`status/on-hold`'u kaldırın; sorun testlerdeyse `ai-test` koyun."
)


def duzeltme_govdesi(task_run: TaskRun, baslik: str, ek: str = "") -> str:
    from backend.config import settings

    cr = task_run.coding_results or {}
    ozet = cr.get("response") or ""
    if isinstance(ozet, dict):  # CLI ajani: yalnizca son mesaj
        ozet = ozet.get("output") or ""
    ozet = (ozet if isinstance(ozet, str) else str(ozet)).strip()[:6000]
    kosu = f"{settings.app_base_url.rstrip('/')}/runs/{task_run.id}"
    return (
        f"## {baslik}\n\n"
        + (ozet or "_Ajan özet bırakmadı._")
        + ek
        + f"\n\n---\nAjan: {cr.get('agent') or '?'}"
        + (f" · Model: {cr['model']}" if cr.get("model") else "")
        + f" · Koşu: [#{task_run.id}]({kosu}) · AgenticKode"
    ).replace("@", "@​")  # kendi yorumu yeni kosu tetiklemesin

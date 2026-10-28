# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: PR etiketleri (acilista) ve istege bagli AI incelemesi (yalnizca Gitea)."""

import contextlib
import logging
import re

logger = logging.getLogger("agentickode.phases.bimetri_etiket")

ZORLUKLAR = ("trivial", "easy", "medium", "hard")
_KARSI_AJAN = {"claude": "codex", "codex": "claude"}
_KAPANIS_RX = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)")


def issue_no_bul(pr_govdesi: str | None) -> int | None:
    """PR aciklamasindaki ilk "Closes #N"."""
    m = _KAPANIS_RX.search(pr_govdesi or "")
    return int(m.group(1)) if m else None


def ajan_adi(deger: str | None) -> str | None:
    """'agent/claude@agent-1' -> 'claude'."""
    if not deger:
        return None
    return deger.split("/", 1)[-1].split("@", 1)[0].strip().lower() or None


def grup_degeri(etiketler: list[str], onek: str) -> str | None:
    """'difficulty/' grubundaki etiketin degeri ('medium'), yoksa None."""
    return next((e.split("/", 1)[1] for e in etiketler if e.startswith(onek)), None)


async def etiketler(gp, rp: str, n: int | None) -> list[str]:
    """Issue ya da PR'in guncel etiketleri; okunamazsa bos liste."""
    if not n:
        return []
    try:
        r = await gp._client.get(
            f"{gp._base_url}/api/v1/repos/{rp}/issues/{int(n)}/labels",
            headers=gp._headers(),
            timeout=30.0,
        )
        r.raise_for_status()
        return [la.get("name", "") for la in r.json()]
    except Exception:
        logger.warning("%s#%s etiketleri okunamadi", rp, n, exc_info=True)
        return []


async def pr_acilis_etiketleri(
    gp, rp: str, pr_no: int, issue_no: int | None, yazan: str | None, mvnw: bool
) -> list[str]:
    """Yeni PR'a: difficulty/* issue'dan, test-agent/* issue'dan ya da yazanin tersi, sonra
    ai-test (mvnw varsa) ya da issue'da ai-review varsa ai-review. Konan etiketleri dondurur."""
    issue_et = await etiketler(gp, rp, issue_no)
    konan = []
    zorluk = grup_degeri(issue_et, "difficulty/")
    if zorluk:
        konan.append(f"difficulty/{zorluk}")
    if mvnw:
        test_ajani = grup_degeri(issue_et, "test-agent/") or _KARSI_AJAN.get(ajan_adi(yazan) or "")
        if test_ajani:
            konan.append(f"test-agent/{test_ajani}")
        konan.append("ai-test")  # en son: test kosusu diger etiketleri hazir bulsun
    elif "ai-review" in issue_et:
        konan.append("ai-review")
    for e in konan:
        await gp.add_label(rp, pr_no, e)
    return konan


async def inceleme_istendi(gp, rp: str, pr_no: int, issue_no: int | None) -> bool:
    """AI incelemesi istege bagli: issue'da ya da PR'da ai-review varsa."""
    if "ai-review" in await etiketler(gp, rp, pr_no):
        return True
    return "ai-review" in await etiketler(gp, rp, issue_no)


async def inceleme_baslat(gp, rp: str, pr_no: int) -> None:
    """ai-review'u kaldirip yeniden koy: label_updated webhook'u inceleme kosusu acar."""
    for e in ("ai-reviewed", "ai-review"):
        with contextlib.suppress(Exception):
            await gp.remove_label(rp, pr_no, e)
    await gp.add_label(rp, pr_no, "ai-review")

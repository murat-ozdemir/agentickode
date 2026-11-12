# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: CI kapisi - zincirin sonunda dev.yml PR'in son commit'i icin bir kez baslatilir.

PR olaylarinda CI kendiliginden kosmaz; workflow_dispatch ile baslar ve sonucunu commit'e
``ci-kapisi`` durumu olarak kendisi yazar. Branch korumasi bu durumu ister: durum yoksa ya da
pending kaldiysa merge kapali kalir (fail-closed).
Repoda (PR dalinda) dev.yml yoksa CI kapisi sessizce atlanir: kit henuz girmemis repo.
"""

import logging
import re

logger = logging.getLogger("agentickode.phases.bimetri_ci")

CI_BAGLAM = "ci-kapisi"
CI_WORKFLOW = "dev.yml"
# Test ajani gerekmeyen degisiklik: yalnizca belge dosyalari
_BELGE_RX = re.compile(r"(?i)(\.(md|adoc|rst|txt)$|(^|/)docs?/|(^|/)LICENSE[^/]*$)")


def belge_yalniz(dosyalar: list[str]) -> bool:
    """Degisen dosyalarin hepsi belge mi (bos liste: bilinmiyor -> hayir)."""
    return bool(dosyalar) and all(_BELGE_RX.search(d) for d in dosyalar)


async def pr_dosyalari(gp, rp: str, n: int) -> list[str]:
    """PR'da degisen dosyalar; okunamazsa bos liste."""
    try:
        r = await gp._client.get(
            f"{gp._base_url}/api/v1/repos/{rp}/pulls/{n}/files",
            params={"limit": 100},
            headers=gp._headers(),
            timeout=30.0,
        )
        r.raise_for_status()
        return [d.get("filename", "") for d in r.json()]
    except Exception:
        logger.warning("%s PR #%s dosyalari okunamadi", rp, n, exc_info=True)
        return []


async def ajan_testi_gerekli(gp, rp: str, n: int, mvnw: bool) -> bool:
    """Test ajani kossun mu: mvnw var ve degisiklik yalnizca belge degil."""
    return mvnw and not belge_yalniz(await pr_dosyalari(gp, rp, n))


async def ci_baslat(gp, rp: str, n: int) -> str:
    """PR'in son commit'i icin CI'i baslatir. O commit'te ci-kapisi durumu zaten varsa
    yeniden baslatmaz. Basarisizlikta PR'a yorum yazar (merge kapali kalir). Sonucu dondurur."""
    try:
        r = await gp._client.get(
            f"{gp._base_url}/api/v1/repos/{rp}/pulls/{n}", headers=gp._headers(), timeout=30.0
        )
        r.raise_for_status()
        head = r.json().get("head") or {}
        sha, dal = head.get("sha", ""), head.get("ref", "")
        # No workflow on the PR branch: the repo has no CI kit yet, nothing to start or warn about
        r = await gp._client.get(
            f"{gp._base_url}/api/v1/repos/{rp}/contents/.gitea/workflows/{CI_WORKFLOW}",
            params={"ref": dal},
            headers=gp._headers(),
            timeout=30.0,
        )
        if r.status_code == 404:
            return f"CI atlandi: {dal} dalinda .gitea/workflows/{CI_WORKFLOW} yok"
        r = await gp._client.get(
            f"{gp._base_url}/api/v1/repos/{rp}/commits/{sha}/status",
            headers=gp._headers(),
            timeout=30.0,
        )
        if r.status_code == 200 and any(
            s.get("context") == CI_BAGLAM for s in r.json().get("statuses") or []
        ):
            return f"CI bu commit icin zaten var ({sha[:8]})"
        r = await gp._client.post(
            f"{gp._base_url}/api/v1/repos/{rp}/actions/workflows/{CI_WORKFLOW}/dispatches",
            headers=gp._headers(),
            json={"ref": dal, "inputs": {"sha": sha}},
            timeout=30.0,
        )
        if r.status_code != 204:
            raise RuntimeError(f"HTTP {r.status_code}")
        return f"CI baslatildi ({sha[:8]})"
    except Exception as exc:
        logger.warning("%s PR #%s CI baslatilamadi", rp, n, exc_info=True)
        try:
            await gp.post_pr_comment(
                rp,
                n,
                f"## CI başlatılamadı\n\n`{CI_WORKFLOW}` tetiklenemedi: {exc}\n\n"
                f"`{CI_BAGLAM}` durumu olmadan PR birleştirilemez. Actions → dev → "
                '"Run workflow" ile PR dalını ve son commit\'i girerek elle başlatın.',
            )
        except Exception:
            logger.warning("%s PR #%s CI yorumu yazilamadi", rp, n, exc_info=True)
        return f"CI baslatilamadi: {exc}"

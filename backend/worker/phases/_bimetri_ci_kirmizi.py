# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: kirmizi CI kapisi botun PR'inda otomatik duzeltme turu acar.

Gitea ``status`` webhook'u ``ci-kapisi`` failure/error gelince: commit'in acik PR'i bulunur,
CI logunun hata satirlari alinir ve otomatik tur yorumu yazilir (yorumu gitea-pr-comment
webhook'u duzeltme kosusuna cevirir). Tur sayaci ve on-hold kurallari test/inceleme ile ortak.
"""

import logging
import re

from backend.worker.phases._bimetri_ci import CI_BAGLAM, CI_WORKFLOW
from backend.worker.phases._bimetri_oto import OTO_YORUM, oto_tur_karari

logger = logging.getLogger("agentickode.phases.bimetri_ci_kirmizi")

CI_ISARET = "<!-- agentickode-ci:{sha} -->"
_LOG_SATIR = 60
_LOG_KARAKTER = 6000
_ZAMAN_RX = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_RENK_RX = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# Maven, surefire, gitleaks ve kabuk hatalari
_HATA_RX = re.compile(
    r"\[ERROR\]|BUILD FAILURE|Tests run:.*(Failures: [1-9]|Errors: [1-9])|leaks found|"
    r"(?i:\berror\b|exception|failed)"
)


async def _json(gp, yol: str, **params):
    r = await gp._client.get(
        f"{gp._base_url}/api/v1{yol}", params=params or None, headers=gp._headers(), timeout=30.0
    )
    r.raise_for_status()
    return r


async def sha_pr(gp, rp: str, sha: str) -> dict | None:
    """Son commit'i ``sha`` olan acik PR."""
    r = await _json(gp, f"/repos/{rp}/pulls", state="open", limit=50)
    return next((p for p in r.json() if (p.get("head") or {}).get("sha") == sha), None)


def log_ozeti(metin: str) -> str:
    """Logdaki hata satirlari (yoksa son satirlar), zaman damgasi ve renk kodu olmadan."""
    satirlar = [_ZAMAN_RX.sub("", _RENK_RX.sub("", s)) for s in metin.splitlines()]
    hatali = [s for s in satirlar if _HATA_RX.search(s)]
    secilen = (hatali or satirlar)[-_LOG_SATIR:]
    return "\n".join(secilen)[-_LOG_KARAKTER:]


async def ci_log(gp, rp: str, sha: str) -> str:
    """Commit icin son dev koşusunun basarisiz isinin log ozeti; okunamazsa bos."""
    try:
        runs = (await _json(gp, f"/repos/{rp}/actions/runs", head_sha=sha, limit=5)).json()
        runs = [
            k
            for k in runs.get("workflow_runs") or []
            if CI_WORKFLOW in (k.get("path") or CI_WORKFLOW)
        ]
        if not runs:
            return ""
        run_id = max(k.get("id", 0) for k in runs)
        jobs = (await _json(gp, f"/repos/{rp}/actions/runs/{run_id}/jobs")).json().get("jobs") or []
        job = next((j for j in jobs if j.get("conclusion") == "failure"), jobs[0] if jobs else None)
        if not job:
            return ""
        return log_ozeti((await _json(gp, f"/repos/{rp}/actions/jobs/{job['id']}/logs")).text)
    except Exception:
        logger.warning("%s %s CI logu okunamadi", rp, sha[:8], exc_info=True)
        return ""


async def ci_kirmizi(gp, rp: str, sha: str, hedef: str = "") -> str:
    """Kirmizi CI: botun PR'inda tur karari verilirse duzeltme yorumu yazar. Sonucu dondurur."""
    pr = await sha_pr(gp, rp, sha)
    if not pr:
        return "acik PR yok"
    n = int(pr["number"])
    isaret = CI_ISARET.format(sha=sha)
    yorumlar = (await _json(gp, f"/repos/{rp}/issues/{n}/comments")).json()
    if any(isaret in (c.get("body") or "") for c in yorumlar):
        return "bu commit icin zaten yazildi"
    if not await oto_tur_karari(gp, rp, n, f"CI kaldı (`{CI_BAGLAM}`)"):
        return "otomatik tur yok"
    log = (await ci_log(gp, rp, sha)).replace("@", "@\u200b").replace("~~~", "~ ~ ~")
    govde = (
        OTO_YORUM.format(neden="CI kaldı; aşağıdaki hatayı gider.")
        + isaret
        + f"\n## CI kaldı ({sha[:8]})\n\n"
        + (f"Koşu: {hedef}\n\n" if hedef else "")
        + (f"~~~\n{log}\n~~~" if log else "_Log okunamadı; koşu sayfasına bak._")
    )
    await gp.post_pr_comment(rp, n, govde)
    return f"PR #{n} icin duzeltme turu istendi"

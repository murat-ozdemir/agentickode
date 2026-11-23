# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a review that only finds missing or wrong tests starts a test round.

The fix agent may not touch tests, so sending such findings to it only stops the chain.
Instead the review comment carries ``TEST_ROUND_MARKER`` (and ``OTO_ISARET``, so the round
counts toward ``OTO_TUR_SINIRI``), the PR gets ``ai-test``, and the test run's prompt gets the
review's findings (``test_request_section``).
"""

import logging
import re

from backend.worker.phases._bimetri_oto import OTO_ISARET

logger = logging.getLogger("agentickode.phases.bimetri_test_round")

TEST_ROUND_MARKER = "<!-- agentickode-test-round -->"
TEST_REPORT_HEADING = "## AI Test Raporu"
_TEST_PATH_RX = re.compile(r"(/src/test/|(^|/)tests?/|Tests?\.\w+\b|(^|/)test_\w+\.py)")
_TAG_RX = re.compile(r"^\s*[-*]\s*\[test\]", re.I)
_LINK_RX = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)|`([^`\s]+\.\w+(?::\d+)?)`")
_FINDINGS_RX = re.compile(r"^#+\s*(Bulgular|Issues)\s*$", re.I | re.M)

TEST_ROUND_PREFIX = (
    "İnceleme yalnızca test eksiği buldu; düzeltme yerine test turu başlıyor (`ai-test`). "
    "Test ajanı aşağıdaki bulgular için test yazacak.\n" + OTO_ISARET + TEST_ROUND_MARKER + "\n\n"
)


def _findings(summary: str) -> list[str]:
    """Bullet lines under the review's findings heading, up to the next heading."""
    m = _FINDINGS_RX.search(summary or "")
    if not m:
        return []
    out = []
    for line in summary[m.end() :].splitlines():
        if line.lstrip().startswith("#"):
            break
        if re.match(r"^\s*[-*]\s+", line):
            out.append(line)
    return out


def _is_test_finding(line: str) -> bool:
    if _TAG_RX.match(line):
        return True
    m = _LINK_RX.search(line)
    path = (m.group(1) or m.group(2)) if m else ""
    return bool(path and _TEST_PATH_RX.search(path))


def only_test_findings(summary: str) -> bool:
    """True when the review has findings and every one is about tests."""
    found = _findings(summary)
    return bool(found) and all(_is_test_finding(x) for x in found)


def _clean(body: str) -> str:
    for marker in (OTO_ISARET, TEST_ROUND_MARKER):
        body = body.replace(marker, "")
    return body.replace(TEST_ROUND_PREFIX.split("\n")[0], "").strip()


async def test_request_section(run, session) -> str:
    """The review findings a test round was started for; empty when this run was not one."""
    meta = run.task_source_meta or {}
    n = meta.get("pr_number")
    if run.git_provider != "gitea" or not n:
        return ""
    try:
        from backend.services.git import get_git_provider
        from backend.services.http_client import get_http_client
        from backend.worker.phases._helpers import get_project_token

        gp = get_git_provider(
            "gitea", get_http_client(), access_token=await get_project_token(run, session)
        )
        rp = meta.get("repo_full_name") or f"{run.repo_owner}/{run.repo_name}"
        r = await gp._client.get(
            f"{gp._base_url}/api/v1/repos/{rp}/issues/{int(n)}/comments",
            headers=gp._headers(),
            timeout=30.0,
        )
        r.raise_for_status()
        request = ""
        for c in r.json():
            body = c.get("body") or ""
            if TEST_ROUND_MARKER in body:
                request = body
            elif TEST_REPORT_HEADING in body:
                request = ""  # already answered by a later test report
    except Exception:
        logger.warning("Run #%s: test round request not read", run.id, exc_info=True)
        return ""
    if not request:
        return ""
    return (
        "\n\n## İncelemenin istediği testler (bu test turunun nedeni)\n"
        "Son AI incelemesi yalnızca test eksiği buldu. Bu bulguları karşılayan testleri yaz. "
        "Yazamadığın bulguyu (ör. başka repoda kalan davranış, repoda olmayan belge) "
        "raporunda gerekçesiyle ayrı ayrı belirt.\n\n<review>\n"
        + _clean(request)[:8000]
        + "\n</review>\n"
    )

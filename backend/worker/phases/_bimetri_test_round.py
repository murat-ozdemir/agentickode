# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a review that only finds missing or wrong tests starts a test round.

The fix agent may not touch tests, so sending such findings to it only stops the chain.
Instead the review comment carries ``TEST_ROUND_MARKER`` (and ``OTO_ISARET``, so the round
counts toward ``OTO_TUR_SINIRI``), the PR gets ``ai-test``, and the test run's prompt gets the
review's findings (``test_request_section``).

A test run after a fix round that closed review findings gets those findings too, as regression
tests to write: the test rules otherwise keep the agent to the issue's acceptance criteria, so
the bug the review found would stay untested.
"""

import logging
import re

from backend.worker.phases._bimetri_oto import OTO_ISARET

logger = logging.getLogger("agentickode.phases.bimetri_test_round")

TEST_ROUND_MARKER = "<!-- agentickode-test-round -->"
TEST_REPORT_HEADING = "## AI Test Raporu"
FIX_PUSHED = "Düzeltme push edildi"
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


def pick_request(bodies: list[str]) -> tuple[str, str] | None:
    """What the next test run answers, from the PR comments in order: ("test_round", the
    review comment) or ("regression", the review findings a pushed fix closed); None once a
    later test report answered it."""
    request: tuple[str, str] | None = None
    fix_review = ""
    for body in bodies:
        if TEST_ROUND_MARKER in body:
            request, fix_review = ("test_round", _clean(body)), ""
        elif OTO_ISARET in body and _findings(body):
            fix_review = body  # a fix round started for these review findings
        elif FIX_PUSHED in body and fix_review:
            request, fix_review = ("regression", "\n".join(_findings(fix_review))), ""
        elif TEST_REPORT_HEADING in body:
            request = None
    return request


_HEADINGS = {
    "test_round": (
        "\n\n## İncelemenin istediği testler (bu test turunun nedeni)\n"
        "Son AI incelemesi yalnızca test eksiği buldu. Bu bulguları karşılayan testleri yaz. "
    ),
    "regression": (
        "\n\n## Düzeltilen inceleme bulguları (regresyon testi)\n"
        "Bu test koşusu bir düzeltme turundan sonra geliyor; aşağıdaki inceleme bulguları "
        "uygulama kodunda düzeltildi. Her bulgu için düzeltilmiş davranışı doğrulayan bir "
        "regresyon testi yaz; bu testler 'kriterlerin dışında test yazma' kuralının "
        "istisnasıdır. "
    ),
}


async def test_request_section(run, session) -> str:
    """The review findings this test run answers; empty when it answers none."""
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
        request = pick_request([c.get("body") or "" for c in r.json()])
    except Exception:
        logger.warning("Run #%s: test round request not read", run.id, exc_info=True)
        return ""
    if not request:
        return ""
    kind, text = request
    return (
        _HEADINGS[kind]
        + "Yazamadığın bulguyu (ör. başka repoda kalan davranış, repoda olmayan belge) "
        "raporunda gerekçesiyle ayrı ayrı belirt.\n\n<review>\n" + text[:8000] + "\n</review>\n"
    )

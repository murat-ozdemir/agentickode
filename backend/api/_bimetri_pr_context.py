# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: give the PR-comment fix run what was written since the last run.

Without this the fix agent only sees the triggering comment, so a request like
"fix the findings" refers to review text the agent never receives. Loop efficiency item 7:
the chain's history (decisions, answers, outcomes) now comes from the chain notebook
(backend/worker/phases/_bimetri_notebook.py); this section carries only the last run's report
and the comments and reviews written after it.
"""

import logging
import re
from typing import Any

logger = logging.getLogger("agentickode.webhooks.pr_context")

ENTRY_CHARS = 12000
START_MARKER = "<!-- agentickode-start -->"  # _bimetri_start_note.START_MARKER
AUTO_MARKER = "<!-- agentickode-oto -->"  # _bimetri_oto.OTO_ISARET: the report is in the trigger

# The fix agent skipped "Oneriler" items and changed nothing because the review said
# "Birlestirilebilir"; the user asking for a fix is the decision.
FINDINGS_RULE = (
    'Yorum incelemedeki bulgularin duzeltilmesini istiyorsa son AI incelemesinin "Bulgular" ve '
    '"Oneriler" maddelerinin hepsi kastedilir; "Kapsam disi" maddeler yalnizca yorum acikca '
    'isterse. Incelemenin sonucu "Birlestirilebilir" olsa, madde dusuk onemli ya da soru olarak '
    "yazilmis olsa da her maddeyi kodda duzelt; duzeltilip duzeltilmeyecegine sen karar verme, "
    "kullanici istedi. Bir maddeyi yapamiyorsan (repoda olmayan bilgi ya da urun karari "
    "gerekiyorsa) son mesajinda o madde icin nedenini yaz."
)

# A platform run report (test report, review, fix outcome, stop notice, CI) starts a new round.
_REPORT = re.compile(
    r"^## (AI Test Raporu|AI Kod İncelemesi|AI Kod Incelemesi|Düzeltme|Koşu durdu|CI )"
)


def is_report(body: str) -> bool:
    return bool(_REPORT.match(body))


def since_last_report(entries: list[tuple[str, bool, str]]) -> list[str]:
    """Texts in time order from the newest run report on; all of them when there is none."""
    entries = sorted(entries, key=lambda e: e[0])
    last = max((i for i, (_, report, _) in enumerate(entries) if report), default=0)
    return [text[:ENTRY_CHARS] for _, _, text in entries[last:]]


async def _get_json(provider: Any, url: str) -> Any:
    resp = await provider._client.get(url, headers=provider._headers(), timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _author(item: dict) -> str:
    return (item.get("user") or {}).get("login", "?")


async def _review_entries(
    provider: Any, api: str, pr_number: int, before_time: str
) -> list[tuple[str, str]]:
    """Formal reviews (body + inline comments) as (timestamp, text) pairs."""
    entries: list[tuple[str, str]] = []
    reviews = await _get_json(provider, f"{api}/pulls/{pr_number}/reviews") or []
    for review in reviews:
        when = review.get("submitted_at") or ""
        if before_time and when > before_time:
            continue
        parts = []
        if (review.get("body") or "").strip():
            parts.append(review["body"].strip())
        if review.get("comments_count"):
            inline = await _get_json(
                provider, f"{api}/pulls/{pr_number}/reviews/{review['id']}/comments"
            )
            for c in inline or []:
                line = c.get("position") or c.get("original_position") or "?"
                parts.append(f"- `{c.get('path', '?')}:{line}` {(c.get('body') or '').strip()}")
        if parts:
            head = f"### {_author(review)} — inceleme ({review.get('state', '')})"
            entries.append((when, head + "\n\n" + "\n".join(parts)))
    return entries


async def pr_discussion(provider: Any, repo_path: str, pr_number: int, trigger: dict) -> str:
    """The last run's report and the comments and reviews written after it, up to the
    triggering comment (``trigger``, the webhook's comment object), oldest first.

    Returns "" for an automatic round (its trigger carries the report) or when nothing was
    fetched.
    """
    if AUTO_MARKER in (trigger.get("body") or ""):
        return ""
    api = f"{provider._base_url}/api/v1/repos/{repo_path}"
    before_id = int(trigger.get("id") or 0)
    before_time = trigger.get("created_at") or ""
    entries: list[tuple[str, bool, str]] = []
    try:
        comments = await _get_json(provider, f"{api}/issues/{pr_number}/comments") or []
        for c in comments:
            body = (c.get("body") or "").strip()
            if START_MARKER in body:  # a run's start note says nothing to the agent
                continue
            if body and (not before_id or int(c.get("id") or 0) < before_id):
                when = c.get("created_at") or ""
                entries.append((when, is_report(body), f"### {_author(c)} — {when}\n\n{body}"))
    except Exception:
        logger.warning("PR comments unavailable (%s#%s)", repo_path, pr_number, exc_info=True)
    try:
        reviews = await _review_entries(provider, api, pr_number, before_time)
        entries += [(when, False, text) for when, text in reviews]
    except Exception:
        logger.warning("PR reviews unavailable (%s#%s)", repo_path, pr_number, exc_info=True)
    return "\n\n".join(since_last_report(entries))


def discussion_section(discussion: str) -> str:
    """Description block for the fix run; empty when there is no discussion."""
    if not discussion:
        return ""
    return (
        "\n\nSon kosunun raporu ve ondan sonra yazilan yorumlar asagida (eskiden yeniye); "
        "zincirin onceki kararlari defterdedir. Yorumdaki "
        '"bulgular", "inceleme", "test raporu" gibi atiflar bunlari kasteder. '
        + FINDINGS_RULE
        + "\n\n"
        # blank lines keep the tag a separate HTML block, so the UI still renders the Markdown
        "<pr_discussion>\n\n" + discussion + "\n\n</pr_discussion>"
    )

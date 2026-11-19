# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri yamasi: give the PR-comment fix run the PR's earlier discussion.

Without this the fix agent only sees the triggering comment, so a request like
"fix the findings" refers to review text the agent never receives.
"""

import logging
from typing import Any

logger = logging.getLogger("agentickode.webhooks.pr_context")

MAX_CONTEXT_CHARS = 30000

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
    """Comments and reviews written before the triggering comment, oldest first.

    ``trigger`` is the webhook's comment object. Oldest entries are dropped first
    when the text exceeds ``MAX_CONTEXT_CHARS``. Returns "" when nothing was fetched.
    """
    api = f"{provider._base_url}/api/v1/repos/{repo_path}"
    before_id = int(trigger.get("id") or 0)
    before_time = trigger.get("created_at") or ""
    entries: list[tuple[str, str]] = []
    try:
        comments = await _get_json(provider, f"{api}/issues/{pr_number}/comments") or []
        for c in comments:
            body = (c.get("body") or "").strip()
            if body and (not before_id or int(c.get("id") or 0) < before_id):
                when = c.get("created_at") or ""
                entries.append((when, f"### {_author(c)} — {when}\n\n{body}"))
    except Exception:
        logger.warning("PR comments unavailable (%s#%s)", repo_path, pr_number, exc_info=True)
    try:
        entries += await _review_entries(provider, api, pr_number, before_time)
    except Exception:
        logger.warning("PR reviews unavailable (%s#%s)", repo_path, pr_number, exc_info=True)

    texts = [text for _, text in sorted(entries, key=lambda e: e[0])]
    while texts and sum(len(t) for t in texts) > MAX_CONTEXT_CHARS:
        texts.pop(0)
    return "\n\n".join(texts)


def discussion_section(discussion: str) -> str:
    """Description block for the fix run; empty when there is no discussion."""
    if not discussion:
        return ""
    return (
        "\n\nPR'daki onceki yorumlar ve incelemeler asagida (eskiden yeniye). Yorumdaki "
        '"bulgular", "inceleme", "test raporu" gibi atiflar bunlari kasteder. '
        + FINDINGS_RULE
        + "\n\n"
        # blank lines keep the tag a separate HTML block, so the UI still renders the Markdown
        "<pr_discussion>\n\n" + discussion + "\n\n</pr_discussion>"
    )

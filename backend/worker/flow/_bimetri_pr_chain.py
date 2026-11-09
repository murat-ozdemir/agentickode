# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: a merged PR's history as plain text, for memory proposals.

Everything the agent chain leaves behind ends up as PR comments: AI review findings, the
agent's final message of each fix run, red-CI log excerpts, failure reasons and
``@agentickode`` commands. Collected: PR title/body, the first linked issue ("Closes #N"),
PR comments and review bodies in time order. Returns "" when the PR has no discussion.
"""

import re

MAX_CHARS = 12000
MAX_ENTRY_CHARS = 1500
_CLOSES = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)")


async def _get_json(provider, path: str, params: dict | None = None):
    # GiteaProvider has no comment-list helpers; same access pattern as _bimetri_ci_kirmizi.
    resp = await provider._client.get(
        f"{provider._base_url}/api/v1/repos/{path}",
        headers=provider._headers(),
        params=params or {},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _clip(text: str, limit: int = MAX_ENTRY_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " [...]"


def _login(item: dict) -> str:
    return (item.get("user") or {}).get("login", "")


async def collect_pr_chain(provider, repo_path: str, pr: dict) -> str:
    number = int(pr["number"])
    comments = await _get_json(provider, f"{repo_path}/issues/{number}/comments", {"limit": 50})
    reviews = await _get_json(provider, f"{repo_path}/pulls/{number}/reviews", {"limit": 50})
    entries = [(c.get("created_at", ""), _login(c), c.get("body", "")) for c in comments or []]
    entries += [
        (r.get("submitted_at", ""), _login(r), r.get("body", ""))
        for r in reviews or []
        if (r.get("body") or "").strip()
    ]
    entries = [e for e in entries if (e[2] or "").strip()]
    if not entries:
        return ""

    parts = [f"# PR #{number}: {pr.get('title', '')}\n\n{_clip(pr.get('body') or '', 3000)}"]
    linked = _CLOSES.search(pr.get("body") or "")
    if linked:
        try:
            issue = await _get_json(provider, f"{repo_path}/issues/{linked.group(1)}")
            parts.append(
                f"## Linked issue #{linked.group(1)}: {issue.get('title', '')}\n\n"
                + _clip(issue.get("body") or "", 3000)
            )
        except Exception:
            pass  # the issue is context only; the discussion is what matters
    parts.append("## Discussion (oldest first)")
    parts += [f"[{when[:16]} {who}]\n{_clip(body)}" for when, who, body in sorted(entries)]
    return "\n\n".join(parts)[:MAX_CHARS]

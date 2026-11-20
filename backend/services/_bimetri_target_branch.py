# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: the runs of a project work on one shared project branch.

The plan agent creates ``proje/<CODE>`` in each repo of the project and writes
``**Hedef dal:** proje/<CODE>`` into every issue. A run for such an issue
branches off the project branch and opens its PR against it; PR runs (review,
test, fix) follow the PR's base branch. The project branch reaches the default
branch later through one human-reviewed PR, after the test environment passes.

Gitea closes ``Closes #N`` issues only for merges into the default branch, so a
merge into a project branch closes the linked issues here.
"""

import logging
import re

logger = logging.getLogger("agentickode.webhooks")

# "Hedef dal: x", "**Hedef dal:** `x`", "<strong>Hedef dal:</strong> x", "Target branch: x"
_LINE = re.compile(
    r"(?im)^[\s>*_-]*(?:<[a-z]+>\s*)*(?:hedef\s+dal|target\s+branch)[ \t]*:?"
    r"[ \t*_:]*(?:</[a-z]+>)?[ \t*_:]*`?([^\s`*<]+)"
)
_VALID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _valid_branch(name: str) -> bool:
    return (
        bool(_VALID.match(name))
        and ".." not in name
        and "//" not in name
        and not name.endswith(("/", ".", ".lock"))
    )


def target_branch(text: str | None) -> str | None:
    """The branch named on the issue's ``Hedef dal:`` line, or None."""
    m = _LINE.search(text or "")
    if not m:
        return None
    name = m.group(1).rstrip(".,;:)")
    if not _valid_branch(name):
        if name:
            logger.warning("Ignoring invalid target branch %r", name)
        return None
    return name


def run_base_branch(default: str, description: str | None, meta: dict | None) -> str:
    """Base branch of a new run: the PR's base for PR runs, else the issue's target."""
    meta = meta or {}
    pr_base = str(meta.get("pr_base_branch") or "")
    if pr_base:
        return pr_base
    if meta.get("pr_number"):
        return default
    return target_branch(description) or default


def merged_off_default(pr: dict, default_branch: str) -> bool:
    """True when the PR was merged into a branch other than the default branch."""
    base = (pr.get("base") or {}).get("ref") or ""
    return bool(base) and base != default_branch


async def close_issues(provider, repo_path: str, numbers: list[int]) -> list[int]:
    """Close the given issues (idempotent); returns the numbers that were closed."""
    closed = []
    api = f"{provider._base_url}/api/v1/repos/{repo_path}/issues"
    for n in numbers:
        try:
            r = await provider._client.patch(
                f"{api}/{n}", headers=provider._headers(), json={"state": "closed"}, timeout=30.0
            )
            r.raise_for_status()
            closed.append(n)
        except Exception:
            logger.warning("#%s could not be closed", n, exc_info=True)
    return closed

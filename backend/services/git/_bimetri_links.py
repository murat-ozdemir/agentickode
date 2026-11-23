# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: file links in agent text point at the branch on Gitea.

Agents (Codex, Claude) write file references as markdown links to the workspace path,
e.g. ``[Foo.java](/workspaces/Org/repo/src/Foo.java:42)``. Gitea resolves such a target
under the repo URL (``/Org/repo/workspaces/Org/repo/...``) and the link is a 404. This
module rewrites those targets to ``<repo web url>/src/branch/<branch>/<path>#L42``.
"""

import logging
import re
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("agentickode.git_provider")

# First path segments that are Gitea repo routes, not files: a relative link starting with
# one of these already resolves under the repo URL, so it is left alone.
_REPO_ROUTES = frozenset(
    {
        "issues",
        "pulls",
        "src",
        "commit",
        "commits",
        "compare",
        "wiki",
        "releases",
        "tags",
        "branches",
        "actions",
        "labels",
        "milestones",
        "attachments",
        "raw",
        "media",
        "projects",
        "packages",
        "settings",
        "activity",
    }
)

# [text](target "title") and [text](<target>)
_INLINE = re.compile(r"(\]\(\s*)(<?)([^)\s<>]+)(>?)((?:\s+\"[^\"]*\")?\s*\))")
# [ref]: target
_REFDEF = re.compile(r"(?m)^(\s{0,3}\[[^\]]+\]:\s*)(<?)(\S+?)(>?)(\s|$)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# path:42, path:42-50, path:42:7 (column dropped)
_LINE = re.compile(r":(\d+)(?:-(\d+))?(?::\d+)?$")


def _repo_relative(target: str, owner: str, repo: str) -> tuple[str, str] | None:
    """Return (repo-relative path, anchor) for a file target, or None to keep it as is."""
    t = target[7:] if target.startswith("file://") else target
    if not t or t.startswith(("#", "//", "?")) or _SCHEME.match(t):
        return None
    path, _, frag = t.partition("#")
    anchor = f"#{frag}" if frag else ""
    m = _LINE.search(path)
    if m:
        path = path[: m.start()]
        if not anchor:
            anchor = f"#L{m.group(1)}" + (f"-L{m.group(2)}" if m.group(2) else "")
    if path.startswith("/"):
        marker = f"/{owner}/{repo}/"
        idx = path.find(marker)
        if idx == 0:
            return None  # already a Gitea host-relative link (/Org/repo/issues/1)
        if idx > 0:
            rel = path[idx + len(marker) :]
        elif path.startswith("/workspaces/"):
            rel = path[len("/workspaces/") :].partition("/")[2]  # cluster: /workspaces/<task>/
        else:
            return None
    else:
        rel = path[2:] if path.startswith("./") else path
        if rel.startswith("../") or rel.split("/", 1)[0] in _REPO_ROUTES:
            return None
    rel = rel.strip("/")
    return (rel, anchor) if rel else None


def fix_file_links(body: str, repo_web_url: str, owner: str, repo: str, branch: str) -> str:
    """Point markdown file links at ``repo_web_url/src/branch/<branch>/<path>``.

    Plain (non-link) mentions of ``/workspaces/<owner>/<repo>/`` lose that prefix so the
    text shows the repo-relative path.
    """
    if not body:
        return body
    base = f"{repo_web_url.rstrip('/')}/src/branch/{quote(branch, safe='/')}/"

    def _sub(m: re.Match) -> str:
        found = _repo_relative(m.group(3), owner, repo)
        if not found:
            return m.group(0)
        rel, anchor = found
        url = base + quote(rel, safe="/") + anchor
        return f"{m.group(1)}{m.group(2)}{url}{m.group(4)}{m.group(5)}"

    body = _INLINE.sub(_sub, body)
    body = _REFDEF.sub(_sub, body)
    return body.replace(f"/workspaces/{owner}/{repo}/", "")


def has_file_links(body: str, owner: str, repo: str) -> bool:
    """True when fix_file_links would change the body (no API call needed otherwise)."""
    return bool(body) and fix_file_links(body, "x:", owner, repo, "b") != body


async def link_files_in_body(
    gp: Any, repo_path: str, body: str, number: int | None = None, branch: str | None = None
) -> str:
    """Rewrite file links in a body about to be posted to Gitea; on any error keep the body.

    ``gp`` is a GiteaProvider. The branch is ``branch`` (new PR), else the PR's head branch,
    else the issue's ref (written when its PR opens), else the repo's default branch.
    """
    owner, _, repo = repo_path.partition("/")
    if not has_file_links(body, owner, repo):
        return body
    api = f"{gp._base_url}/api/v1/repos/{repo_path}"
    try:
        r = await gp._client.get(api, headers=gp._headers(), timeout=30.0)
        r.raise_for_status()
        info = r.json()
        web = info.get("html_url") or f"{gp._base_url}/{repo_path}"
        if not branch and number:
            r = await gp._client.get(f"{api}/pulls/{number}", headers=gp._headers(), timeout=30.0)
            if r.status_code == 200:
                branch = (r.json().get("head") or {}).get("ref")
            else:
                r = await gp._client.get(
                    f"{api}/issues/{number}", headers=gp._headers(), timeout=30.0
                )
                if r.status_code == 200:
                    branch = (r.json().get("ref") or "").removeprefix("refs/heads/")
        branch = branch or info.get("default_branch") or "master"
        return fix_file_links(body, web, owner, repo, branch)
    except Exception:
        logger.warning("File links not rewritten for %s #%s", repo_path, number, exc_info=True)
        return body

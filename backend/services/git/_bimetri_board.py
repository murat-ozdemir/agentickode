# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: keep Gitea project board cards in step with the status/* label.

Every org or repo project the issue belongs to gets its card moved to the column
for the new status. Columns are matched by title (case-insensitive); a project
without a matching column is left alone. Issues without ``ai-task`` never get a
status label, so they stay wherever the planner put them (usually Backlog).
"""

import logging
from typing import Any

logger = logging.getLogger("agentickode.git_provider")

# status label -> accepted column titles, first match wins
STATUS_COLUMNS: dict[str, tuple[str, ...]] = {
    "status/open": ("to do", "todo"),
    "status/in-progress": ("in progress",),
    "status/review": ("review", "in review"),
    "status/completed": ("done",),
    "status/on-hold": ("on hold",),
}


def project_api_base(api: str, repo_path: str, project: dict[str, Any]) -> str | None:
    """API base of a project that holds an issue of ``repo_path``; None for user projects."""
    kind = project.get("type")
    pid = project.get("id")
    if not pid:
        return None
    if kind == "organization":
        return f"{api}/orgs/{repo_path.split('/', 1)[0]}/projects/{pid}"
    if kind == "repository":
        return f"{api}/repos/{repo_path}/projects/{pid}"
    return None


def column_for(columns: list[dict[str, Any]], label: str | None) -> dict[str, Any] | None:
    """Column a card with ``label`` belongs in, or None."""
    wanted = STATUS_COLUMNS.get(label or "")
    if not wanted:
        return None
    by_title = {(c.get("title") or "").strip().lower(): c for c in columns}
    return next((by_title[t] for t in wanted if t in by_title), None)


async def move_issue_card(
    client: Any, api: str, headers: dict[str, str], repo_path: str, number: int, label: str | None
) -> list[str]:
    """Move the issue's card on each of its project boards; returns the moved project titles."""
    if label not in STATUS_COLUMNS:
        return []
    r = await client.get(f"{api}/repos/{repo_path}/issues/{number}", headers=headers, timeout=30.0)
    if r.status_code != 200:
        return []
    issue = r.json()
    moved: list[str] = []
    for project in issue.get("projects") or []:
        base = project_api_base(api, repo_path, project)
        if base is None:
            continue
        rc = await client.get(
            f"{base}/columns", headers=headers, params={"limit": 50}, timeout=30.0
        )
        if rc.status_code != 200:
            continue
        column = column_for(rc.json(), label)
        if column is None:
            continue
        rm = await client.post(
            f"{base}/issues/{issue['id']}/move",
            headers=headers,
            json={"column_id": column["id"]},
            timeout=30.0,
        )
        if rm.status_code in (200, 201, 204):
            moved.append(project.get("title") or str(project.get("id")))
        else:
            logger.warning(
                "Board card not moved: %s #%s -> %r (HTTP %s)",
                repo_path,
                number,
                column.get("title"),
                rm.status_code,
            )
    return moved

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: the PR review agent works inside the repo clone, on the PR branch.

pr_review is a generate-mode flow, so the executor skipped workspace setup and the CLI ran
in the worker user's home. The code-graph MCP server needs a git clone as its cwd, so every
review said the graph server could not connect and saw only the diff. Here the review
also syncs the clone and checks out the PR branch (init does that when pr_head_branch is
set); if that fails the review goes on with the diff alone.

The engine runs one run per (project, workspace server) at a time, so syncing the clone
cannot reset the work of a test or fix run on the same clone.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskRun
from backend.services.container import ServiceContainer
from backend.worker.broadcaster import broadcaster

RunPhase = Callable[[str, TaskRun, AsyncSession, ServiceContainer], Awaitable[None]]

# claude --print asks for permission before MCP tools and Bash; without a terminal that is a
# denial, and the graph gate hook then closes every other tool too. Read-only set only.
REVIEW_ALLOWED_TOOLS = (
    "mcp__bimetri-graph",
    "Read",
    "Grep",
    "Glob",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git show:*)",
)

REVIEW_CLONE_RULES = (
    "- Repo klonu PR dalında açık; çalışma dizinin onun kökü. Diff'teki şüphelerini (çağıranlar, "
    "silinen ya da yeniden adlandırılan sembollerin kullanımları, ilgili testler) önce kod "
    "grafiğiyle (`graph_continue`, gerekirse `graph_callers`), sonra dosyaları okuyarak doğrula; "
    "doğrulayamadığını bulgu yazma.\n"
    "- Dosya değiştirme, commit ya da push yapma; yalnızca oku.\n"
    "- Kod grafiği ya da klon kullanılamıyorsa bunu bir cümleyle belirt ve diff ile devam et.\n"
)


async def prepare_review_clone(
    run: TaskRun, session: AsyncSession, services: ServiceContainer, run_phase: RunPhase
) -> str | None:
    """Sync the clone and check out the PR branch; the clone path, or None on failure."""
    try:
        await run_phase("workspace_setup", run, session, services)
        await run_phase("init", run, session, services)
    except Exception as exc:
        await broadcaster.log(
            run.id,
            f"İnceleme klonu hazırlanamadı, yalnızca diff ile devam: {exc}",
            level="warning",
            phase="agent",
        )
        return None
    return str(run.workspace_path) if run.workspace_path else None

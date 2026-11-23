# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): agent-call tokens with the graph against a pre-graph baseline.

The Code graph card's saved share only covers file reads; the quota goes on turns times context.
This compares whole agent calls. Each graph call (``metadata_.graph`` set) is matched with the
median tokens (in + out) of calls made before the first graph call:

1. same task (``pr-comment-114-4734`` and ``pr-comment-114-4791`` are one task), agent and phase;
2. else same repo, agent and phase, when at least ``MIN_REPO_SAMPLES`` calls exist.

Calls with neither are left out and counted apart. ``saved_pct`` is signed: a negative value
means the graph calls cost more than their baseline.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any

MIN_REPO_SAMPLES = 3
_COMMENT_TASK = re.compile(r"^(pr-comment-\d+)-\d+$")


@dataclass
class TokenRow:
    started_at: datetime
    repo: str
    task_id: str
    agent: str
    phase: str
    tokens: int
    turns: int | None
    graph: bool


def task_key(task_id: str) -> str:
    """One task for all review-comment runs of a PR."""
    match = _COMMENT_TASK.match(task_id)
    return match[1] if match else task_id


def _family(agent: str) -> str:
    return agent.split("/", 1)[0]


def build(rows: list[TokenRow], since: datetime | None) -> dict[str, Any]:
    graph_rows = [r for r in rows if r.graph]
    cutoff = min((r.started_at for r in graph_rows), default=None)
    by_task: dict[tuple, list[int]] = {}
    by_repo: dict[tuple, list[int]] = {}
    for r in rows:
        if r.graph or cutoff is None or r.started_at >= cutoff:
            continue
        kind = (_family(r.agent), r.phase)
        by_task.setdefault((task_key(r.task_id), *kind), []).append(r.tokens)
        by_repo.setdefault((r.repo, *kind), []).append(r.tokens)

    actual = baseline = same_task = same_repo = 0
    shown = [r for r in graph_rows if since is None or r.started_at >= since]
    turns = [r.turns for r in shown if r.turns is not None]
    for r in shown:
        kind = (_family(r.agent), r.phase)
        task_pool = by_task.get((task_key(r.task_id), *kind))
        repo_pool = by_repo.get((r.repo, *kind), [])
        if task_pool:
            same_task += 1
            pool = task_pool
        elif len(repo_pool) >= MIN_REPO_SAMPLES:
            same_repo += 1
            pool = repo_pool
        else:
            continue
        actual += r.tokens
        baseline += int(median(pool))
    return {
        "graph_calls": len(shown),
        "compared": same_task + same_repo,
        "same_task": same_task,
        "same_repo": same_repo,
        "actual_tokens": actual,
        "baseline_tokens": baseline,
        "saved_pct": round(100 * (baseline - actual) / baseline) if baseline else None,
        "turns_per_call": round(sum(turns) / len(turns), 1) if turns else None,
    }

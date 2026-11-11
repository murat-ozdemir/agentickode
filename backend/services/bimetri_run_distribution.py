# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Task Distribution card — sorts runs by server, agent, model and so on.

Pure functions over plain rows, so the card's counts and the Runs list filter built on the
same rows always agree.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

RANGES: dict[str, int | None] = {"7d": 7, "30d": 30, "all": None}
DIMENSIONS = ("server", "agent", "model", "difficulty", "type", "outcome")

NO_SERVER = "no server"
NO_AGENT = "no agent call"
UNKNOWN_MODEL = "unknown"
NO_LABEL = "no label"

_TYPE_BY_REVIEW_MODE = {"comment": "review", "test": "test", "fix": "fix"}
_DIFFICULTY_ORDER = ["trivial", "easy", "medium", "hard", NO_LABEL]
_TYPE_ORDER = ["task", "test", "fix", "review"]


@dataclass
class RunRow:
    id: int
    created_at: datetime
    status: str
    meta: dict[str, Any]
    server: str | None
    # (agent_name, model) of the run's invocations, oldest first
    calls: list[tuple[str, str | None]] = field(default_factory=list)


def since_for(range_key: str, today: date) -> date | None:
    days = RANGES[range_key]
    return None if days is None else today - timedelta(days=days - 1)


def classify(row: RunRow) -> dict[str, str | None]:
    """One value per dimension; model is None for runs that never called an agent."""
    labels = row.meta.get("labels") or []
    difficulty = next(
        (
            lb.split("/", 1)[1]
            for lb in labels
            if isinstance(lb, str) and lb.startswith("difficulty/")
        ),
        NO_LABEL,
    )
    agent, model = row.calls[0] if row.calls else (NO_AGENT, None)
    return {
        "server": row.server or NO_SERVER,
        "agent": agent,
        "model": (model or UNKNOWN_MODEL) if row.calls else None,
        "difficulty": difficulty,
        "type": _TYPE_BY_REVIEW_MODE.get(str(row.meta.get("review_mode") or ""), "task"),
        "outcome": row.status,
    }


def matching_ids(rows: list[RunRow], dim: str, value: str) -> list[int]:
    return [r.id for r in rows if classify(r)[dim] == value]


def _ordered(dim: str, counts: dict[str, int]) -> list[str]:
    fixed = {"difficulty": _DIFFICULTY_ORDER, "type": _TYPE_ORDER}.get(dim)
    if fixed:
        return [v for v in fixed if v in counts or v != NO_LABEL] + sorted(
            v for v in counts if v not in fixed
        )
    tail = {NO_SERVER, NO_AGENT, UNKNOWN_MODEL}
    return sorted(counts, key=lambda v: (v in tail, -counts[v], v))


def build(rows: list[RunRow], since: date | None, today: date) -> dict[str, Any]:
    classes = [(r, classify(r)) for r in rows]
    first = since or min((r.created_at.date() for r in rows), default=today)
    day_index = {first + timedelta(days=i): i for i in range((today - first).days + 1)}
    days: list[dict[str, Any]] = [
        {"date": d.isoformat(), "total": 0, "by": {k: {} for k in DIMENSIONS}} for d in day_index
    ]
    counts: dict[str, dict[str, int]] = {k: {} for k in DIMENSIONS}
    finished: dict[str, list[int]] = {}  # server -> [completed, completed+failed]

    for row, cls in classes:
        slot = day_index.get(row.created_at.date())
        if slot is not None:
            days[slot]["total"] += 1
        for dim, value in cls.items():
            if value is None:
                continue
            counts[dim][value] = counts[dim].get(value, 0) + 1
            if slot is not None:
                by = days[slot]["by"][dim]
                by[value] = by.get(value, 0) + 1
        if row.status in ("completed", "failed"):
            ok = finished.setdefault(cls["server"] or NO_SERVER, [0, 0])
            ok[0] += row.status == "completed"
            ok[1] += 1

    groups = {}
    for dim in DIMENSIONS:
        items = []
        for value in _ordered(dim, counts[dim]):
            item: dict[str, Any] = {"name": value, "count": counts[dim].get(value, 0)}
            if dim == "server" and value in finished:
                done, total = finished[value]
                item["ok_pct"] = round(done / total * 100)
            items.append(item)
        groups[dim] = items
    return {"total": len(rows), "since": first.isoformat(), "days": days, "groups": groups}

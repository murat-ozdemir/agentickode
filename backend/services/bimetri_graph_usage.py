# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): Code graph card — graph use and estimated token savings.

Pure functions over plain rows. Each agent call's ``metadata_["graph"]`` block comes from
backend/worker/flow/_bimetri_graph_calls.py. Saved share is 1 - returned / full characters,
the part of the pointed-at files the graph kept out of the agent's context. Both are computed
from the characters, so they go negative when the graph sent more than the files hold (older
rows stored a saved_tokens clamped at zero).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from backend.config import DEFAULT_COST_RATE, MODEL_COST_RATES
from backend.worker.flow._bimetri_graph_calls import saved_tokens

NO_SERVER = "no server"


@dataclass
class GraphRow:
    run_id: int
    created_at: datetime
    server: str | None
    # (agent_name, graph block or None) of the run's agent calls
    calls: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)


@dataclass
class _Sum:
    runs: int = 0
    calls: int = 0
    saved_tokens: int = 0
    returned_chars: int = 0
    full_chars: int = 0
    saved_usd: float = 0.0

    def add(self, graph: dict[str, Any], agent: str) -> None:
        saved = saved_of(graph)
        self.calls += int(graph.get("calls") or 0)
        self.saved_tokens += saved
        self.returned_chars += int(graph.get("returned_chars") or 0)
        self.full_chars += int(graph.get("full_chars") or 0)
        self.saved_usd += saved * input_price(agent) / 1_000_000

    def out(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "calls": self.calls,
            "saved_tokens": self.saved_tokens,
            "saved_usd": round(self.saved_usd, 2),
            "returned_chars": self.returned_chars,
            "full_chars": self.full_chars,
            "saved_pct": saved_pct(self.returned_chars, self.full_chars),
        }


def input_price(agent: str) -> float:
    """USD per 1M input tokens of the agent ("ollama/qwen" -> "ollama")."""
    return MODEL_COST_RATES.get(agent.split("/", 1)[0], DEFAULT_COST_RATE)[0]


def saved_of(graph: dict[str, Any]) -> int:
    """Signed saved tokens of one graph block, from its characters."""
    return saved_tokens(int(graph.get("full_chars") or 0), int(graph.get("returned_chars") or 0))


def saved_pct(returned: int, full: int) -> int | None:
    """Signed: below zero when the graph sent more characters than the files hold."""
    if full <= 0:
        return None
    return round(100 * (full - returned) / full)


def build(rows: list[GraphRow], since: date | None, today: date) -> dict[str, Any]:
    total = _Sum()
    by_server: dict[str, _Sum] = {}
    by_agent: dict[str, int] = {}
    per_day: dict[str, int] = {}
    for row in rows:
        graphs = [(agent, g) for agent, g in row.calls if g]
        if not graphs:
            continue
        server = by_server.setdefault(row.server or NO_SERVER, _Sum())
        total.runs += 1
        server.runs += 1
        for agent in dict.fromkeys(agent for agent, _ in graphs):
            by_agent[agent] = by_agent.get(agent, 0) + 1
        day = row.created_at.date().isoformat()
        for agent, graph in graphs:
            total.add(graph, agent)
            server.add(graph, agent)
            per_day[day] = per_day.get(day, 0) + saved_of(graph)
    first = since or min(
        (r.created_at.date() for r in rows if any(g for _, g in r.calls)), default=today
    )
    days = [
        {"date": d.isoformat(), "saved_tokens": per_day.get(d.isoformat(), 0)}
        for d in (first + timedelta(days=i) for i in range((today - first).days + 1))
    ]
    return {
        "total_runs": len(rows),
        "since": first.isoformat(),
        "totals": total.out(),
        "agents": dict(sorted(by_agent.items(), key=lambda kv: (-kv[1], kv[0]))),
        "days": days,
        "workers": [
            {"name": name, **s.out()}
            for name, s in sorted(by_server.items(), key=lambda kv: (-kv[1].saved_tokens, kv[0]))
        ],
    }

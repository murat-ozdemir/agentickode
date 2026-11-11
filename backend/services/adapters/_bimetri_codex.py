# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Codex ``exec --json`` output — final message, token usage, ChatGPT credits.

Codex runs on a ChatGPT plan, so a run has no dollar cost. The credits it spends are
computed from the per-model rates in the codex agent's ``CODEX_CREDIT_RATES`` env var
(credits per 1M tokens, ``model=input/cached_input/output``, comma separated).
"""

from __future__ import annotations

import json
from typing import Any

RATES_ENV = "CODEX_CREDIT_RATES"
DEFAULT_CREDIT_RATES = (
    "gpt-6-astra=250/25/1250,gpt-6.1-sol=50/2.5/250,"
    "gpt-6.1-terra=25/1.25/125,gpt-6-luna=2.5/0.25/12.5"
)
_TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
_CODEX_EVENTS = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "item.completed",
}


def _events(stdout: str) -> list[dict[str, Any]]:
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and isinstance(event.get("type"), str):
            events.append(event)
    return events


def parse_jsonl(stdout: str) -> tuple[str | None, dict[str, Any]] | None:
    """(last agent message, usage) from ``codex exec --json``; None if stdout is not its JSONL.

    ``cached_input_tokens`` is part of ``input_tokens``. Usage is summed over
    ``turn.completed`` events (``codex exec`` runs a single turn).
    """
    events = _events(stdout)
    if not any(e["type"] in _CODEX_EVENTS for e in events):
        return None
    message: str | None = None
    totals = dict.fromkeys(_TOKEN_KEYS, 0)
    has_usage = False
    for event in events:
        item = event.get("item")
        if (
            event["type"] == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            message = item["text"]
        usage = event.get("usage")
        if event["type"] == "turn.completed" and isinstance(usage, dict):
            has_usage = True
            for key in _TOKEN_KEYS:
                totals[key] += int(usage.get(key) or 0)
    result: dict[str, Any] = {"cost_usd": None, "billing": "chatgpt"}
    if has_usage:
        result.update(totals)
    return message, result


def parse_rates(spec: str | None) -> dict[str, tuple[float, float, float]]:
    """``model=in/cached/out,...`` → {model: (in, cached, out)}; malformed entries are skipped."""
    rates: dict[str, tuple[float, float, float]] = {}
    for part in (spec or "").split(","):
        name, _, numbers = part.partition("=")
        try:
            inp, cached, out = (float(n) for n in numbers.split("/"))
        except ValueError:
            continue
        if name.strip():
            rates[name.strip()] = (inp, cached, out)
    return rates


def add_credits(usage: dict[str, Any] | None, model: str | None, env: dict | None) -> None:
    """Add ``codex_credits`` to a Codex usage dict; left out for an unknown model or no usage."""
    if not usage or usage.get("billing") != "chatgpt" or usage.get("input_tokens") is None:
        return
    rate = parse_rates((env or {}).get(RATES_ENV) or DEFAULT_CREDIT_RATES).get(model or "")
    if rate is None:
        return
    cached = usage.get("cached_input_tokens") or 0
    uncached = (usage.get("input_tokens") or 0) - cached
    output = usage.get("output_tokens") or 0
    usage["codex_credits"] = round(
        (uncached * rate[0] + cached * rate[1] + output * rate[2]) / 1_000_000, 4
    )

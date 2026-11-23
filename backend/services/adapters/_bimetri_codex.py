# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Codex ``exec --json`` output — final message, token usage, ChatGPT credits.

Codex runs on a ChatGPT plan, so it is billed in credits. The credits a call spends are
computed from the per-model rates in the codex agent's ``CODEX_CREDIT_RATES`` env var
(credits per 1M tokens, ``model=input/cached_input/output``, comma separated). Their dollar
equivalent uses the price of one credit in ``CODEX_CREDIT_USD``, so Codex shows up in the
cost totals next to Claude.
"""

from __future__ import annotations

import json
import re
from typing import Any

RATES_ENV = "CODEX_CREDIT_RATES"
PRICE_ENV = "CODEX_CREDIT_USD"
DEFAULT_CREDIT_USD = "0.04"
DEFAULT_CREDIT_RATES = (
    "gpt-6-astra=250/25/1250,gpt-6.1-sol=50/2.5/250,"
    "gpt-6.1-terra=25/1.25/125,gpt-6-luna=2.5/0.25/12.5"
)
_TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
_NOT_TOOL_ITEMS = ("agent_message", "reasoning", "todo_list", "error")
# A shell command that prints a source file (graf tasarruf planı Faz 1: Codex has no hook to send
# it to graph_read, so these are counted and shown on the Code graph card).
_SOURCE_READ = re.compile(
    r"\b(?:cat|bat|nl|less|more|head|tail|sed\s+-n)\b[^|;&]*?"
    r"\.(?:java|kts?|py|tsx?|jsx?|go|cs|scala|groovy)\b"
)
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


def _failure(events: list[dict[str, Any]]) -> str | None:
    """Why the turn failed (usage limit, credits, ...): ``turn.failed`` error, else the last
    top-level ``error`` event when no turn completed (retry notices of a finished turn are not
    failures)."""
    failed = [e for e in events if e["type"] == "turn.failed"]
    if failed:
        error = failed[-1].get("error")
        text = error.get("message") if isinstance(error, dict) else error
        if isinstance(text, str) and text.strip():
            return text.strip()
    if any(e["type"] == "turn.completed" for e in events):
        return None
    for event in reversed(events):
        text = event.get("message")
        if event["type"] == "error" and isinstance(text, str) and text.strip():
            return text.strip()
    return None


def parse_jsonl(stdout: str) -> tuple[str | None, dict[str, Any]] | None:
    """(last agent message, usage) from ``codex exec --json``; None if stdout is not its JSONL.

    ``cached_input_tokens`` is part of ``input_tokens``. Usage is summed over
    ``turn.completed`` events (``codex exec`` runs a single turn). ``turns`` counts the model's
    steps as Claude's ``num_turns`` does: one per tool item (command, file change, MCP call, ...)
    plus the final answer. ``shell_reads`` counts commands that print a source file. When the turn failed, the message is the failure text instead, so
    the run-stopped comment shows the real reason.
    """
    events = _events(stdout)
    if not any(e["type"] in _CODEX_EVENTS for e in events):
        return None
    message: str | None = None
    totals: dict[str, int] = dict.fromkeys(_TOKEN_KEYS, 0)
    has_usage = False
    tool_items = shell_reads = 0
    for event in events:
        item = event.get("item")
        if (
            event["type"] == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            message = item["text"]
        elif event["type"] == "item.completed" and isinstance(item, dict):
            tool_items += item.get("type") not in _NOT_TOOL_ITEMS
            command = item.get("command") if item.get("type") == "command_execution" else None
            shell_reads += isinstance(command, str) and bool(_SOURCE_READ.search(command))
        usage = event.get("usage")
        if event["type"] == "turn.completed" and isinstance(usage, dict):
            has_usage = True
            for key in _TOKEN_KEYS:
                totals[key] += int(usage.get(key) or 0)
    result: dict[str, Any] = {"cost_usd": None, "billing": "chatgpt"}
    if has_usage:
        result.update(totals)
        result["turns"] = tool_items + 1
        result["shell_reads"] = shell_reads
    return _failure(events) or message, result


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
    """Add ``codex_credits`` and their dollar equivalent ``cost_usd`` to a Codex usage dict.

    Both are left out for an unknown model or no usage; ``cost_usd`` also for a bad price.
    """
    if not usage or usage.get("billing") != "chatgpt" or usage.get("input_tokens") is None:
        return
    env = env or {}
    rate = parse_rates(env.get(RATES_ENV) or DEFAULT_CREDIT_RATES).get(model or "")
    if rate is None:
        return
    cached = usage.get("cached_input_tokens") or 0
    uncached = (usage.get("input_tokens") or 0) - cached
    output = usage.get("output_tokens") or 0
    usage["codex_credits"] = round(
        (uncached * rate[0] + cached * rate[1] + output * rate[2]) / 1_000_000, 4
    )
    try:
        price = float(env.get(PRICE_ENV) or DEFAULT_CREDIT_USD)
    except ValueError:
        return
    usage["cost_usd"] = round(usage["codex_credits"] * price, 6)

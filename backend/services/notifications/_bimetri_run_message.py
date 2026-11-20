# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: run start/finish/failure messages that say what the run is.

Each message names the run type (with its own emoji), the issue and PR, the server,
the agent and the result, in Turkish. Plain text, so Slack, Discord and Telegram
show it the same way.
"""

import re
from typing import Any

RUN_EVENTS = ("run_started", "run_completed", "run_failed")

_KINDS = {
    "task": ("🛠️", "Kodlama"),
    "test": ("🧪", "Test"),
    "review": ("🔍", "İnceleme"),
    "fix": ("🔧", "Düzeltme"),
}
# results that need a human look even though the run itself completed
_WARN_OUTCOMES = {"Testler kaldı", "Test edilemedi", "Değişiklik gerekli"}
_TITLE_PREFIX = re.compile(r"^(?:\[PR #\d+\]\s*)?(?:Test:\s*|Review PR #\d+:\s*)?")


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _subject(kind: str, data: dict[str, Any]) -> str:
    """Issue line for a coding run; PR (and its issue) line for the PR runs."""
    title = _one_line(_TITLE_PREFIX.sub("", str(data.get("title") or "")))
    issue = data.get("issue_number")
    pr = data.get("pr_number")
    if kind == "task" or not pr:
        ref = f"Issue #{issue}" if issue else ""
        name = title
    else:
        ref = f"PR #{pr}" + (f" (Issue #{issue})" if issue and str(issue) != str(pr) else "")
        # a fix run's title is the PR comment; the PR's own name says what it is about
        name = str(data.get("pr_title") or "") if kind == "fix" else (data.get("pr_title") or title)
    return "📌 " + " — ".join(p for p in (ref, _one_line(str(name))) if p)


def _info(data: dict[str, Any], duration: str) -> str:
    agent = data.get("agent")
    if agent and data.get("model"):
        agent = f"{agent} ({data['model']})"
    parts = [f"Koşu #{data.get('run_id', '?')}", data.get("server"), agent]
    if duration:
        parts.append(f"⏱️ {duration}")
    return "⚙️ " + " · ".join(str(p) for p in parts if p)


def format_run_message(event_type: str, data: dict[str, Any], link: str, duration: str) -> str:
    kind = str(data.get("run_kind") or "task")
    emoji, name = _KINDS.get(kind, _KINDS["task"])
    repo = data.get("repo") or data.get("project_id") or ""
    outcome = data.get("outcome")

    if event_type == "run_started":
        head = f"{emoji} {name} başladı"
    elif event_type == "run_failed":
        head = f"❌ {emoji} {name} başarısız"
    else:
        status = "⚠️" if outcome in _WARN_OUTCOMES else "✅"
        head = f"{status} {emoji} {name} bitti"
    lines = [f"{head} · {repo}" if repo else head, _subject(kind, data)]

    if kind == "fix" and event_type == "run_started":
        reason = _one_line(_TITLE_PREFIX.sub("", str(data.get("title") or "")))
        if reason:
            lines.append(f"💬 Sebep: {reason}")
    if event_type == "run_failed":
        lines.append(f"⚠️ {_one_line(str(data.get('error') or 'Bilinmeyen hata'))[:300]}")
    if event_type == "run_completed":
        if outcome:
            lines.append(f"📋 Sonuç: {outcome}")
        if data.get("pr_url"):
            lines.append(f"🔀 PR: {data['pr_url']}")
    lines.append(_info(data, duration if event_type != "run_started" else ""))
    lines.append(f"🔗 {link}")
    return "\n".join(lines)

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: upgrade the codex agent row for token usage, ChatGPT credits and their price."""

from __future__ import annotations

from sqlalchemy.orm.attributes import flag_modified

from backend.models import AgentSettings
from backend.services.adapters._bimetri_codex import (
    DEFAULT_CREDIT_RATES,
    DEFAULT_CREDIT_USD,
    PRICE_ENV,
    RATES_ENV,
)


def upgrade_codex(existing: AgentSettings) -> bool:
    """Add ``--json`` after ``codex exec`` and seed the credit env vars; True if changed.

    Other flags in the templates are kept; existing rates and price values are never overwritten.
    """
    if existing.agent_name != "codex":
        return False
    changed = False
    templates = dict(existing.command_templates or {})
    for key, value in templates.items():
        if isinstance(value, str) and "codex exec" in value and "--json" not in value:
            templates[key] = value.replace("codex exec", "codex exec --json", 1)
            changed = True
    if changed:
        existing.command_templates = templates
        flag_modified(existing, "command_templates")
    env = dict(existing.environment_vars or {})
    defaults = {RATES_ENV: DEFAULT_CREDIT_RATES, PRICE_ENV: DEFAULT_CREDIT_USD}
    missing = {k: v for k, v in defaults.items() if k not in env}
    if missing:
        existing.environment_vars = {**env, **missing}
        flag_modified(existing, "environment_vars")
        changed = True
    return changed

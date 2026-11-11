# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: upgrade the codex agent row for token usage and ChatGPT credits."""

from __future__ import annotations

from sqlalchemy.orm.attributes import flag_modified

from backend.models import AgentSettings
from backend.services.adapters._bimetri_codex import DEFAULT_CREDIT_RATES, RATES_ENV


def upgrade_codex(existing: AgentSettings) -> bool:
    """Add ``--json`` after ``codex exec`` and seed the credit rates env var; True if changed.

    Other flags in the templates are kept; an existing rates value is never overwritten.
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
    if RATES_ENV not in env:
        env[RATES_ENV] = DEFAULT_CREDIT_RATES
        existing.environment_vars = env
        flag_modified(existing, "environment_vars")
        changed = True
    return changed

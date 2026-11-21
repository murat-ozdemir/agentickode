# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: 5-hour / weekly limits of the agent subscription accounts on the workers.

A new agent (e.g. Antigravity via opencode) needs a section in ``worker_probe.py`` and an
adapter registered in ``ADAPTERS``; storage, API and the Dashboard strip are provider-neutral.
"""

from backend.services.bimetri_agent_quota.claude_adapter import ClaudeQuotaAdapter
from backend.services.bimetri_agent_quota.codex_adapter import CodexQuotaAdapter
from backend.services.bimetri_agent_quota.types import QuotaAdapter

ADAPTERS: dict[str, QuotaAdapter] = {
    a.provider: a for a in (ClaudeQuotaAdapter(), CodexQuotaAdapter())
}

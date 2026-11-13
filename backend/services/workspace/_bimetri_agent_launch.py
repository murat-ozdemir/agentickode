# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: how a terminal session starts an agent that has no special launch line.

codex starts without ChatGPT-connected apps (Jira, Sites, Supabase...): they come from the
signed-in ChatGPT account, not from the project, and codex reaches for them before the repo.
"""

CODEX_LAUNCH = "codex -c features.apps=false"


def agent_launch_command(agent_name: str) -> str:
    return CODEX_LAUNCH if agent_name == "codex" else agent_name

---
title: bimetri — project-memory MCP for agents (yama 75)
status: implemented
date: 2026-11-09
related: [runbooks/bimetri-mem0-pgvector.md]
---

# bimetri — project-memory MCP for agents (yama 75)

## Goal

Let coding agents search a project's mem0 memory during a run and propose what they learned,
with a human approving every write.

## Scope

In scope:
- Run-start memory section split into three searches: `proje`, knowledge kinds
  (`modul/karar/ders/tuzak/calisma`), `ozellik_gecmisi`; a tool hint when the MCP is enabled.
- `memory-mcp` compose service: read tools plus `propose_memory`, bearer-token guard.
- Agent proposals in `bimetri_memory_proposals` (`source=agent`, `run_id`, nullable `pr_number`),
  shown on the Memory page with a link to the run.
- Worker config script for Claude and Codex; Turkish "Proje hafızası" section in the repo
  AGENTS templates.
- Records tab pagination: API returns `{items, total, offset, limit, kinds}`; the backend reads
  the whole project from mem0 and slices (mem0 `GET /memories` has no offset), 50 per page.

Out of scope:
- Agents writing to mem0 directly, editing or deleting records.
- Per-agent tokens; one shared token for all workers.

## Technical Approach

- `search_memories(project, query, kinds, top_k)` in `backend/services/bimetri_mem0.py`; mem0
  filter `{"tur": {"in": [...]}}` (verified on mem0 v2.2.1).
- FastMCP server `backend/mcp/bimetri_memory_server.py`, stateless streamable HTTP at `/mcp`,
  pure-ASGI `BearerAuth` (`/health` open, empty token refuses all), `mask_error_details=True`.
  Separate from the backend's admin MCP at `/mcp`, which has no auth.
- Tools in `backend/mcp/bimetri_memory_tools.py`: project must be registered in AgenticKode;
  `propose_memory` checks the run belongs to the project, caps 3 proposals per run, skips a text
  already pending.
- Migration `b046_memory_proposal_source`; merge dedup (`exists_for_pr`) looks only at
  `source=merge`.
- `scripts/bimetri/agent-memory-mcp.sh` sends the token over SSH stdin and writes
  `~/.claude.json` (`mcpServers`, user scope) and `~/.codex/config.toml` (`http_headers`) of the
  worker user. `bearer_token_env_var` was not used: the non-interactive SSH session of a run does
  not load the user's shell profile.

## Success Criteria

- [x] Unit/integration tests for the search split, tools, bearer guard, proposals API, script
- [x] Frontend shows Agent/Merge source and the run link
- [x] Records tab pages 50 at a time; kind filter lists every kind of the project
- [x] Deployed on dev-1; `claude mcp list` / `codex mcp list` show `bimetri-memory` on the workers
- [x] A real run log shows the agent calling a memory tool (run #70, platform-backend PR #54: two
  `search_project_memory` calls, one `propose_memory`; run #68 called none because everything it
  needed was already in the run-start section)

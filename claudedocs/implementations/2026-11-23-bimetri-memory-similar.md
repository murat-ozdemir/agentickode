---
title: "bimetri: similar-record check before memory proposals"
status: implemented
date: 2026-11-23
related: [plans/2026-11-09-bimetri-memory-mcp.md, runbooks/bimetri-mem0-pgvector.md]
---

# bimetri: similar-record check before memory proposals

## What Was Built

- `propose_memory` searches mem0 for knowledge records close to the proposed text before queuing it.
- When it finds any, it returns `status: "similar"` with up to three records and queues nothing.
- The agent then has three choices:
  - drop the proposal
  - propose again with `replaces=<id>`, so approval updates that record in place
  - propose again with `force=true` when its text is a new fact
- The Memory page lists the similar records on each proposal. The reviewer can switch between "Replace this" and "Add as new instead".

## Key Files

| File | Purpose |
|------|---------|
| `backend/services/bimetri_mem0.py` | `similar_memories` (semantic-score threshold), `get_memory`, `update_memory` (PUT) |
| `backend/services/bimetri_mem0_similar.py` | `find_similar` (never blocks; errors → None), shared by agent and merge proposals |
| `backend/mcp/_bimetri_memory_similar.py` | `replaced_record` (id belongs to the project) |
| `backend/worker/flow/_bimetri_proposals.py` | Merge (PR discussion) proposals store `similar` too |
| `backend/mcp/bimetri_memory_tools.py` | `propose_memory` `replaces` / `force` flow; search/list results now carry `id` |
| `backend/api/bimetri_memory_proposals.py` | PATCH `replaces_mem0_id` (only an id from `similar`); approve calls `update_memory` instead of `add_memory` |
| `alembic/versions/051_bimetri_memory_proposal_similar.py` | `similar` JSON + `replaces_mem0_id` columns |
| `frontend/src/components/memory/SimilarRecords.tsx` | Similar records with score and the replace toggle |

## How It Works

1. Threshold: `score_details.semantic_score` (cosine, via `explain: true`) ≥ 0.60.
   - mem0's combined score mixes in BM25 and moves with query length, so the check does not use it.
   - Measured on real records:
     - own text: 0.91
     - paraphrases: 0.62–0.85
     - related but new fact: 0.65
     - unrelated: 0.29–0.44
2. A forced or replacing proposal stores the records it matched in `similar`, and the reviewer sees them.
3. When a proposal is approved with `replaces_mem0_id`, mem0's `PUT /memories/{id}` runs. It re-embeds the record and keeps the old text in mem0 history.

## Notes

- Migration 051 must run on deploy.
- Copies of `AGENTS.md` in the project repos need the new "Benzer kayıt" bullet. Only the template in `repo-sablonlari` was changed.
- Proposals from the PR discussion (merge source) are checked too (since 2026-11-23); the agent never sees the result, only the reviewer does.
- `similar` values:
  - `[]`: checked, nothing passed the threshold. The pending card says "No similar records in memory".
  - `null`: not checked (older proposal, or mem0 unreachable). The card says "Not checked against memory".
- An unreachable mem0 never blocks a proposal: it is queued with `similar` null.

---
title: "bimetri: Codex token usage and ChatGPT plan credits"
status: implemented
date: 2026-11-11
related: [plans/2026-11-11-bimetri-codex-credits.md]
---

# bimetri: Codex token usage and ChatGPT plan credits

## What Was Built

Codex runs on the workers sign in with a ChatGPT plan, so a call has no dollar cost. Each Codex call
now records its tokens (input, cached input, output, reasoning output) and the plan credits it spent;
the run page shows them in blue next to the dollar cost of the other agents.

## Key Files

| File | Purpose |
|------|---------|
| `backend/services/adapters/_bimetri_codex.py` | JSONL parsing (`parse_jsonl`), rates (`parse_rates`), credits (`add_credits`), default rates |
| `backend/services/adapters/cli_adapter.py` | Codex branch in `_parse_json_output` |
| `backend/worker/flow/executor.py` | `add_credits` before the invocation record; extras into `metadata_` |
| `backend/seed/_bimetri_codex.py` + `agent_settings.py` | `--json` on codex templates, `CODEX_CREDIT_RATES` env var |
| `frontend/src/utils/codexUsage.ts`, `components/runs/CodexUsageNote.tsx` | Read and render the credits |
| `tests/unit/test_bimetri_codex.py`, `frontend/src/__tests__/CodexUsage.test.tsx` | Tests |

## How It Works

1. Seed adds `--json` after `codex exec` in each codex template and `CODEX_CREDIT_RATES` to the
   agent env (only when missing).
2. `codex exec --json` writes JSONL events. The adapter keeps the last `agent_message` text as the
   result and sums `turn.completed.usage`; `cached_input_tokens` is part of `input_tokens`.
3. The executor looks up the call's model in the rates and stores
   `codex_credits = (uncached × in + cached × cached + out × out) / 1M`.
4. The UI shows `ChatGPT plan · N credits · M cached in`; totals show dollars and credits apart.

Rates format: `model=input/cached/output,...` (credits per 1M tokens), e.g.
`gpt-6.1-terra=25/1.25/125`.

## Notes

- The long-context multipliers are not modelled.
- An unknown model gets no credits ("credits n/a"); add it to the env var on the Agents page.
- Calls before this change have no breakdown and show nothing.
- Still to check on the first real run: `turn.completed.usage` per turn vs cumulative.

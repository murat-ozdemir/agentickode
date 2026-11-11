---
title: "bimetri: Codex token usage and ChatGPT plan credits"
status: implemented
date: 2026-11-11
related: [implementations/2026-11-11-bimetri-codex-credits.md, plans/2026-11-10-bimetri-openai-usage.md]
---

# bimetri: Codex token usage and ChatGPT plan credits

## Goal

Show what a Codex run spent: its tokens (input, cached input, output) and the ChatGPT plan credits,
instead of an empty or made-up dollar figure.

## Scope

**In scope**
- `codex exec --json` on the codex agent's templates; parse its JSONL (final message + usage)
- Credits per call from per-model rates (input / cached input / output, per 1M tokens) kept in the
  codex agent's `CODEX_CREDIT_RATES` env var, editable on the Agents page
- Run page: credits next to the dollar cost, cached tokens in the call details

**Out of scope**
- The long-context 2x / 1.5x multipliers
- Reading the real plan balance (ChatGPT has no API for it)
- Analytics charts (they sum dollars; Codex stays out of them)

## Technical Approach

- Seed upgrade: add `--json` after `codex exec` in every codex template and seed the rates env var
  when absent; never overwrite edits
- `CLIAdapter._parse_json_output`: for codex, read the JSONL events; result = last `agent_message`,
  usage = summed `turn.completed.usage`, `billing: chatgpt`, no `cost_usd`
- Executor: compute `codex_credits` from the model of the call and the agent env, store
  `cached_input_tokens`, `reasoning_output_tokens`, `codex_credits`, `billing` in `metadata_`
- Frontend: `CodexUsageNote` + `utils/codexUsage.ts` in the activity panel, call drawer and cost summary

## Success Criteria

- [x] A codex call stores tokens and credits; `estimated_cost_usd` stays null
- [x] Rates come from the agent env var; an unknown model gets no credits but keeps its tokens
- [x] The dollar total leaves Codex out; credits are shown on their own line
- [ ] First real Codex run checked: usage per turn, not cumulative

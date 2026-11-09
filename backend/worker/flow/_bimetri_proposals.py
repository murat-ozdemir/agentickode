# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: on PR merge, let an LLM propose project-memory records.

The merged PR's discussion (see ``_bimetri_pr_chain``) goes to an OpenAI model, which returns
0-3 lessons / pitfalls / decisions worth remembering. They are stored as ``pending`` rows in
``bimetri_memory_proposals``; nothing reaches mem0 until a human approves one.

Skipped when mem0 or ``MEM0_OPENAI_API_KEY`` is not configured, when the PR already has
proposals, or when the PR has no discussion (no LLM call). Runs in the background so the
webhook response is not delayed; errors are only logged.
"""

import asyncio
import json
import logging

from backend.config import settings
from backend.database import async_session
from backend.models import MemoryProposal
from backend.models.bimetri_memory import PROPOSAL_KINDS
from backend.repositories.memory_proposal_repo import MemoryProposalRepository
from backend.services.bimetri_mem0 import list_memories, mem0_enabled
from backend.services.http_client import get_http_client
from backend.worker.flow._bimetri_pr_chain import collect_pr_chain

logger = logging.getLogger("agentickode.bimetri.proposals")

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MAX_PROPOSALS = 3
MAX_TEXT_CHARS = 600
# mem0 ``metadata.tur`` values used by the existing records and scripts/bimetri tooling.
KIND_TO_TUR = {"lesson": "ders", "pitfall": "tuzak", "decision": "karar"}
_tasks: set[asyncio.Task] = set()

SYSTEM_PROMPT = """You maintain the long-term memory of a software project.
You get the full history of one merged pull request: description, linked issue, AI review
findings, fix-run reports, CI failures and human comments.
Propose at most 3 records worth remembering for FUTURE work in this repository:
- lesson: something that went wrong and how it was fixed, phrased as advice
- pitfall: a non-obvious trap in this codebase (tooling, config, API quirk)
- decision: a design choice made in the discussion, with its reason
Rules: only project-specific, reusable knowledge; skip anything obvious, generic, already
listed under "Existing records" or like the "Rejected" ones; one or two sentences each; name
files/modules when it helps. Do NOT propose:
- a summary of what this PR changed or left unchanged (the feature history records that)
- behaviour this PR removed or fixed (it is no longer true after the merge)
- facts readable from the code, or general practice (write tests, validate inputs)
Proposing nothing is fine. Write the text in {language}.
Answer with JSON only: {{"proposals": [{{"kind": "lesson|pitfall|decision", "text": "..."}}]}}"""


def parse_proposals(content: str) -> list[dict]:
    """Validate the model's JSON answer; drop malformed items, keep at most MAX_PROPOSALS."""
    try:
        items = json.loads(content or "{}").get("proposals") or []
    except (ValueError, AttributeError):
        return []
    result = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        kind, text = item.get("kind"), str(item.get("text") or "").strip()
        if kind in PROPOSAL_KINDS and text:
            result.append({"kind": kind, "text": text[:MAX_TEXT_CHARS]})
    return result[:MAX_PROPOSALS]


async def generate_proposals(
    chain: str, existing: list[str], rejected: list[str] | None = None
) -> list[dict]:
    known = "\n".join(f"- {t}" for t in existing[:100]) or "(none)"
    refused = "\n".join(f"- {t}" for t in (rejected or [])[:30]) or "(none)"
    resp = await get_http_client().post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {settings.mem0_openai_api_key}"},
        json={
            "model": settings.memory_proposal_model,
            "reasoning_effort": "low",
            "response_format": {"type": "json_object"},
            "max_completion_tokens": 16000,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT.format(language=settings.memory_proposal_language),
                },
                {
                    "role": "user",
                    "content": f"Existing records:\n{known}\n\n"
                    f"Rejected by a human earlier:\n{refused}\n\n{chain}",
                },
            ],
        },
        timeout=180.0,
    )
    resp.raise_for_status()
    return parse_proposals(resp.json()["choices"][0]["message"]["content"])


async def propose_for_merge(
    provider, project: str, repo_path: str, pr: dict, session_factory=async_session
) -> str:
    """Return 'disabled', 'exists', 'no-discussion' or 'N proposals'; may raise."""
    if not (mem0_enabled() and settings.mem0_openai_api_key):
        return "disabled"
    number = int(pr["number"])
    async with session_factory() as session:
        repo = MemoryProposalRepository(session)
        if await repo.exists_for_pr(project, number):
            return "exists"
        earlier = await repo.list_proposals(project=project)
        pending = [p.text for p in earlier if p.status == "pending"]
        rejected = [p.text for p in earlier if p.status == "rejected"]
    chain = await collect_pr_chain(provider, repo_path, pr)
    if not chain:
        return "no-discussion"
    tur_values = set(KIND_TO_TUR.values())
    existing = [
        m.get("memory", "")
        for m in await list_memories(project)
        if (m.get("metadata") or {}).get("tur") in tur_values
    ]
    proposals = await generate_proposals(chain, existing + pending, rejected)
    if proposals:
        async with session_factory() as session:
            await MemoryProposalRepository(session).add_all(
                [
                    MemoryProposal(project=project, pr_number=number, source="merge", **p)
                    for p in proposals
                ]
            )
            await session.commit()
    return f"{len(proposals)} proposals"


async def _run(provider, project: str, repo_path: str, pr: dict) -> None:
    number = pr.get("number")
    try:
        outcome = await propose_for_merge(provider, project, repo_path, pr)
        logger.info("PR #%s memory proposals (%s): %s", number, project, outcome)
    except Exception:
        logger.warning("PR #%s memory proposals failed (%s)", number, project, exc_info=True)


def schedule_proposals(provider, project: str, repo_path: str, pr: dict) -> None:
    task = asyncio.create_task(_run(provider, project, repo_path, pr))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

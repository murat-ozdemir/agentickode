# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: minimal mem0 REST client (list, search and add records of one project).

Records live under user_id = "<owner>/<repo>"; ``metadata.tur`` holds the record kind
(proje, modul, ozellik_gecmisi, karar, ders, tuzak). Disabled while MEM0_URL or MEM0_API_KEY
is empty.
"""

from collections.abc import Sequence

from backend.config import settings
from backend.services.bimetri_openai_alert import check_quota
from backend.services.http_client import get_http_client

# What the project is and how it works vs. what was done in which PR. Searched separately so the
# growing per-PR history cannot crowd decisions and lessons out of the results.
KNOWLEDGE_KINDS = ("proje", "modul", "karar", "ders", "tuzak", "calisma")
HISTORY_KINDS = ("ozellik_gecmisi",)


def mem0_enabled() -> bool:
    return bool(settings.mem0_url and settings.mem0_api_key)


def _url(path: str) -> str:
    return f"{settings.mem0_url.rstrip('/')}{path}"


def _headers() -> dict[str, str]:
    return {"X-API-Key": settings.mem0_api_key}


async def list_memories(project: str) -> list[dict]:
    resp = await get_http_client().get(
        _url("/memories"),
        headers=_headers(),
        params={"user_id": project, "top_k": 1000},
        timeout=15.0,
    )
    await check_quota(resp, "mem0")
    resp.raise_for_status()
    body = resp.json()
    return body.get("results", []) if isinstance(body, dict) else body


async def search_memories(
    project: str, query: str, kinds: Sequence[str] = (), top_k: int = 8
) -> list[dict]:
    """Records most similar to ``query``; ``kinds`` limits ``metadata.tur`` (empty: all)."""
    filters: dict = {"user_id": project}
    if len(kinds) == 1:
        filters["tur"] = kinds[0]
    elif kinds:
        filters["tur"] = {"in": list(kinds)}
    resp = await get_http_client().post(
        _url("/search"),
        headers=_headers(),
        json={"query": query, "filters": filters, "top_k": top_k},
        timeout=15.0,
    )
    await check_quota(resp, "mem0")
    resp.raise_for_status()
    body = resp.json()
    return body.get("results", []) if isinstance(body, dict) else body


async def similar_memories(
    project: str, text: str, kinds: Sequence[str], min_similarity: float, top_k: int = 5
) -> list[dict]:
    """Records whose embedding is at least ``min_similarity`` (cosine) close to ``text``.

    mem0's ``score`` mixes in BM25 and is divided by the number of signals, so it moves with the
    query's length (a record searched with its own text scores ~0.5). The semantic part from
    ``explain`` is a plain cosine similarity and is what a duplicate check can threshold on.
    """
    resp = await get_http_client().post(
        _url("/search"),
        headers=_headers(),
        json={
            "query": text,
            "filters": {"user_id": project, "tur": {"in": list(kinds)}},
            "top_k": top_k,
            "explain": True,
        },
        timeout=15.0,
    )
    await check_quota(resp, "mem0")
    resp.raise_for_status()
    body = resp.json()
    rows = body.get("results", []) if isinstance(body, dict) else body
    out = []
    for row in rows:
        details = row.get("score_details") or {}
        similarity = details.get("semantic_score", row.get("score")) or 0.0
        if similarity >= min_similarity:
            out.append(row | {"similarity": float(similarity)})
    return sorted(out, key=lambda r: r["similarity"], reverse=True)


async def get_memory(memory_id: str) -> dict | None:
    """One record by id, or None when mem0 does not have it."""
    resp = await get_http_client().get(
        _url(f"/memories/{memory_id}"), headers=_headers(), timeout=15.0
    )
    if resp.status_code in (400, 404):
        return None
    resp.raise_for_status()
    # mem0 answers an unknown id with 200 and a null body
    return (resp.json() if resp.content else None) or None


async def update_memory(memory_id: str, text: str, metadata: dict) -> None:
    """Replace a record's text in place (re-embedded; mem0 keeps the old text in its history)."""
    resp = await get_http_client().put(
        _url(f"/memories/{memory_id}"),
        headers=_headers(),
        json={"text": text, "metadata": metadata},
        timeout=30.0,
    )
    await check_quota(resp, "mem0")
    resp.raise_for_status()


async def add_memory(project: str, text: str, metadata: dict) -> str | None:
    """Store one record verbatim (infer=False: no LLM, one embedding). Returns its id."""
    resp = await get_http_client().post(
        _url("/memories"),
        headers=_headers(),
        json={
            "messages": [{"role": "user", "content": text}],
            "user_id": project,
            "metadata": metadata,
            "infer": False,
        },
        timeout=30.0,
    )
    await check_quota(resp, "mem0")
    resp.raise_for_status()
    results = (resp.json() or {}).get("results") or [{}]
    return results[0].get("id")

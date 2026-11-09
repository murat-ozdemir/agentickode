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
    resp.raise_for_status()
    body = resp.json()
    return body.get("results", []) if isinstance(body, dict) else body


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
    resp.raise_for_status()
    results = (resp.json() or {}).get("results") or [{}]
    return results[0].get("id")

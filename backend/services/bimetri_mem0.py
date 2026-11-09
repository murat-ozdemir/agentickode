# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: minimal mem0 REST client (list and add records of one project).

Records live under user_id = "<owner>/<repo>"; ``metadata.tur`` holds the record kind
(proje, modul, ozellik_gecmisi, karar, ders, tuzak). Disabled while MEM0_URL or MEM0_API_KEY
is empty.
"""

from backend.config import settings
from backend.services.http_client import get_http_client


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

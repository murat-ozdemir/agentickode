# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: the record an agent proposal replaces (``propose_memory(replaces=...)``).

The similarity search itself lives in ``backend.services.bimetri_mem0_similar``.
"""

import uuid

from fastmcp.exceptions import ToolError

from backend.services.bimetri_mem0 import get_memory
from backend.services.bimetri_mem0_similar import compact


async def replaced_record(project: str, memory_id: str) -> dict:
    """The project's record that a proposal will replace; refuses ids of other projects."""
    try:
        uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(f"replaces must be a record id, got {memory_id!r}") from None
    try:
        row = await get_memory(memory_id)
    except Exception as e:
        raise ToolError(f"mem0 read failed: {e}") from e
    if row is None or row.get("user_id") != project:
        raise ToolError(f"{memory_id} is not a record of {project}")
    return compact(row)

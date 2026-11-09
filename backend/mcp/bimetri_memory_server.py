# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: project-memory MCP for agents (the memory-mcp compose service).

    uvicorn backend.mcp.bimetri_memory_server:app --host 0.0.0.0 --port 8000

Streamable HTTP at /mcp; every request needs "Authorization: Bearer <BIMETRI_MEMORY_MCP_TOKEN>"
and everything is refused while the token is empty. Kept apart from the admin MCP mounted on
the backend at /mcp, which has no auth and must stay unreachable for agents.
"""

import hmac

from fastmcp import FastMCP
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.config import settings
from backend.mcp.bimetri_memory_tools import (
    list_project_memory,
    propose_memory,
    search_project_memory,
)

mcp = FastMCP(
    "bimetri-memory",
    instructions=(
        "Project memory of the repositories AgenticKode works on: earlier decisions, "
        "pitfalls, lessons and PR history. Search before you dig into an unfamiliar area; "
        "propose what you learned that the code does not show. The code wins over a record."
    ),
    tools=[search_project_memory, list_project_memory, propose_memory],
    # Only ToolError messages reach the agent; DB/driver errors stay in the container log.
    mask_error_details=True,
)


class BearerAuth:
    """Pure ASGI guard: lifespan passes through, /health is open, the rest needs the token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode() if token else None

    def _authorized(self, scope: Scope) -> bool:
        if self._expected is None:
            return False
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                return hmac.compare_digest(value, self._expected)
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/health":
            await PlainTextResponse("ok")(scope, receive, send)
        elif scope["type"] == "http" and not self._authorized(scope):
            response = JSONResponse(
                {"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
            await response(scope, receive, send)
        else:
            await self.app(scope, receive, send)


def create_app(token: str) -> ASGIApp:
    return BearerAuth(mcp.http_app(path="/mcp", stateless_http=True), token)


app = create_app(settings.bimetri_memory_mcp_token)

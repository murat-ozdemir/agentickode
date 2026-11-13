# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: stdio MCP server that forwards to the platform's SSE MCP endpoint.

Codex only talks to stdio or streamable HTTP MCP servers, and the platform mounts its tools
over SSE (``/mcp/sse``), so the codex chat agent starts this script as its MCP server.

Usage: python _bimetri_codex_mcp_bridge.py http://localhost:8000/mcp/sse
"""

import sys

from fastmcp.client.transports import SSETransport
from fastmcp.server.server import create_proxy


def main() -> None:
    create_proxy(SSETransport(sys.argv[1])).run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()

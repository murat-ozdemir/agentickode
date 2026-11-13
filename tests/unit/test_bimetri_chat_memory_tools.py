# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: chat agents read project memory (mem0) through the platform MCP."""

from fastmcp import Client

from backend.mcp import server


class TestChatMemoryTools:
    async def test_platform_mcp_offers_read_only_memory_tools(self):
        async with Client(server.mcp) as client:
            names = {t.name for t in await client.list_tools()}
        assert {"search_project_memory", "list_project_memory"} <= names
        assert "propose_memory" not in names

    def test_instructions_name_the_memory_tools(self):
        assert "search_project_memory" in (server.mcp.instructions or "")

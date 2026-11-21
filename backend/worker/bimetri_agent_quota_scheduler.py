# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: refreshes the agent subscription limits on the Dashboard every 10 minutes."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.config import settings
from backend.services.bimetri_agent_quota import service

logger = logging.getLogger("agentickode.bimetri_agent_quota_scheduler")
_IDLE_SECONDS = 600


class AgentQuotaScheduler:
    """Probes every ``settings.agent_quota_poll_seconds``; a value of 0 or less turns it off."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._running = False

    async def tick(self) -> None:
        if settings.agent_quota_poll_seconds <= 0:
            return
        try:
            async with self._session_factory() as session:
                await service.collect(session)
        except Exception:
            logger.exception("Agent quota collection crashed")

    async def run(self) -> None:
        self._running = True
        while self._running:
            await self.tick()
            await asyncio.sleep(max(settings.agent_quota_poll_seconds, 0) or _IDLE_SECONDS)

    def stop(self) -> None:
        self._running = False

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: refreshes the OpenAI spend card from the Costs API every 15 minutes."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.config import settings
from backend.services import bimetri_openai_usage

logger = logging.getLogger("agentickode.bimetri_openai_usage_scheduler")


class OpenAIUsageScheduler:
    """Syncs every ``settings.openai_usage_poll_seconds``; idle while the Admin key is empty."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._running = False

    async def tick(self) -> None:
        if not bimetri_openai_usage.usage_enabled():
            return
        try:
            async with self._session_factory() as session:
                error = await bimetri_openai_usage.sync(session)
            if error:
                logger.warning("OpenAI spend sync failed: %s", error)
        except Exception:
            logger.exception("OpenAI spend sync crashed")

    async def run(self) -> None:
        self._running = True
        while self._running:
            await self.tick()
            await asyncio.sleep(settings.openai_usage_poll_seconds)

    def stop(self) -> None:
        self._running = False

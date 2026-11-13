# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: OpenAI quota alert for mem0 and the memory proposals.

A 429 whose ``error.code`` is ``insufficient_quota`` (spend limit) or
``credit_balance_exhausted`` (no credit left) means every later call fails until someone acts;
``rate_limit_exceeded`` is transient and ignored. mem0 wraps the OpenAI error in its own 500
body, so the response text is searched for the codes. The first such error turns the Dashboard
card red and sends one message to the enabled notification channels; a new credit entry or the
next successful proposal call clears it.
"""

import logging
from datetime import UTC, datetime

import httpx

from backend.database import async_session
from backend.repositories.app_setting_repo import AppSettingRepository
from backend.repositories.notification_channel_repo import NotificationChannelRepository
from backend.services.http_client import get_http_client
from backend.services.notifications.service import NotificationService

logger = logging.getLogger("agentickode.bimetri_openai_alert")

ALERT_KEY = "bimetri.openai.alert"
QUOTA_CODES = ("credit_balance_exhausted", "insufficient_quota")
MESSAGE = (  # Turkish: the team reads the notifications in Turkish
    "OpenAI kredisi bitti\n"
    "mem0 ve hafıza önerileri durdu ({code}, kaynak: {source}). "
    'Kredi yükleyip Dashboard\'daki OpenAI kartında "Kredi ekle" ile girin.'
)


def quota_code(text: str) -> str | None:
    return next((code for code in QUOTA_CODES if code in text), None)


async def record_quota_error(code: str, source: str, session_factory=async_session) -> bool:
    """Store the alert and notify once; False when an alert is already open."""
    async with session_factory() as session:
        repo = AppSettingRepository(session)
        if await repo.get(ALERT_KEY):
            return False
        at = datetime.now(UTC).isoformat()
        await repo.set(ALERT_KEY, {"code": code, "source": source, "at": at})
        channels = await NotificationChannelRepository(session).list_enabled()
    service = NotificationService(get_http_client())
    for channel in channels:
        try:
            await service.send(channel, MESSAGE.format(code=code, source=source))
        except Exception:
            logger.warning("OpenAI quota alert not sent to %s", channel.name, exc_info=True)
    return True


async def check_quota(resp: httpx.Response, source: str, session_factory=async_session) -> None:
    """Record an alert when ``resp`` carries an OpenAI quota error; never raises."""
    if resp.status_code < 400:
        return
    try:
        code = quota_code(resp.text)
        if code:
            await record_quota_error(code, source, session_factory)
    except Exception:
        logger.warning("OpenAI quota alert could not be recorded", exc_info=True)


async def clear_alert(session) -> None:
    repo = AppSettingRepository(session)
    if await repo.get(ALERT_KEY):
        await repo.set(ALERT_KEY, {})


async def clear_alert_quietly(session_factory=async_session) -> None:
    try:
        async with session_factory() as session:
            await clear_alert(session)
    except Exception:
        logger.warning("OpenAI quota alert could not be cleared", exc_info=True)

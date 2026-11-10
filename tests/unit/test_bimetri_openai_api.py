# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: credit entries API and the OpenAI quota alert."""

from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import NotificationChannel
from backend.repositories.app_setting_repo import AppSettingRepository
from backend.services import bimetri_openai_alert as alert

URL = "/api/bimetri/openai"


class TestCredits:
    async def test_add_list_edit_delete(self, client):
        created = await client.post(
            f"{URL}/credits", json={"amount_usd": "10.50", "credited_on": "2026-11-01"}
        )
        assert created.status_code == 201
        credit = created.json()
        assert credit["amount_usd"] == 10.5 and credit["credited_on"] == "2026-11-01"

        edited = await client.patch(f"{URL}/credits/{credit['id']}", json={"amount_usd": "12"})
        assert edited.json()["amount_usd"] == 12.0

        listed = (await client.get(f"{URL}/credits")).json()
        assert [c["id"] for c in listed] == [credit["id"]]
        summary = (await client.get(f"{URL}/summary")).json()
        assert summary["credits_total_usd"] == 12.0 and summary["remaining_usd"] == 12.0

        assert (await client.delete(f"{URL}/credits/{credit['id']}")).status_code == 204
        assert (await client.get(f"{URL}/credits")).json() == []

    async def test_date_defaults_to_today_and_amount_must_be_positive(self, client):
        created = await client.post(f"{URL}/credits", json={"amount_usd": "5"})
        assert created.json()["credited_on"]
        assert (await client.post(f"{URL}/credits", json={"amount_usd": "0"})).status_code == 422

    async def test_missing_entry_is_404(self, client):
        assert (await client.delete(f"{URL}/credits/999")).status_code == 404

    async def test_sync_needs_the_admin_key(self, client, monkeypatch):
        from backend.services import bimetri_openai_usage

        monkeypatch.setattr(bimetri_openai_usage.settings, "openai_admin_key", "")
        assert (await client.post(f"{URL}/sync")).status_code == 409


@pytest.fixture()
def factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
def notify(monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr(alert, "NotificationService", lambda client: service)
    monkeypatch.setattr(alert, "get_http_client", lambda: None)
    return service


def _error(status: int, code: str) -> httpx.Response:
    body = {"detail": f"Error code: {status} - {{'error': {{'code': '{code}'}}}}"}
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://mem0/x"))


class TestQuotaAlert:
    async def test_first_quota_error_notifies_once(self, db_session, factory, notify):
        db_session.add(NotificationChannel(name="slack", channel_type="slack", config={}))
        await db_session.commit()

        await alert.check_quota(_error(500, "insufficient_quota"), "mem0", factory)
        await alert.check_quota(_error(429, "credit_balance_exhausted"), "mem0", factory)

        assert notify.send.await_count == 1
        assert "insufficient_quota" in notify.send.call_args.args[1]
        state = await AppSettingRepository(db_session).get(alert.ALERT_KEY)
        assert state["code"] == "insufficient_quota" and state["source"] == "mem0"

    @pytest.mark.parametrize("resp", [_error(429, "rate_limit_exceeded"), httpx.Response(200)])
    async def test_transient_errors_and_success_are_ignored(
        self, resp, db_session, factory, notify
    ):
        await alert.check_quota(resp, "mem0", factory)
        assert notify.send.await_count == 0
        assert not await AppSettingRepository(db_session).get(alert.ALERT_KEY)

    async def test_summary_shows_the_alert_and_a_credit_clears_it(self, client, factory, notify):
        await alert.record_quota_error("credit_balance_exhausted", "mem0", factory)
        summary = (await client.get(f"{URL}/summary")).json()
        assert summary["alert"]["code"] == "credit_balance_exhausted"

        await client.post(f"{URL}/credits", json={"amount_usd": "20"})
        assert (await client.get(f"{URL}/summary")).json()["alert"] is None

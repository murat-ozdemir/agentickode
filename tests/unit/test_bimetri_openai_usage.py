# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: OpenAI spend from the Costs API, credits and the remaining balance."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.repositories.app_setting_repo import AppSettingRepository
from backend.repositories.openai_usage_repo import OpenAIUsageRepository
from backend.services import bimetri_openai_usage as usage
from backend.worker.bimetri_openai_usage_scheduler import OpenAIUsageScheduler

NOW = datetime(2026, 11, 10, 12, 30, tzinfo=UTC)


def _ts(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def _bucket(day: date, *values: float) -> dict:
    return {
        "object": "bucket",
        "start_time": _ts(day),
        "end_time": _ts(day) + 86400,
        "results": [
            {"object": "organization.costs.result", "amount": {"value": v, "currency": "usd"}}
            for v in values
        ],
    }


def _page(buckets: list, next_page: str | None = None) -> httpx.Response:
    body = {"object": "page", "data": buckets, "has_more": bool(next_page), "next_page": next_page}
    return httpx.Response(200, json=body, request=httpx.Request("GET", usage.COSTS_URL))


@pytest.fixture()
def http(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(usage, "get_http_client", lambda: client)
    monkeypatch.setattr(usage.settings, "openai_admin_key", "admin-test")
    return client


class TestFetchDailyCosts:
    async def test_sums_each_day_and_follows_the_cursor(self, http):
        http.get.side_effect = [
            _page([_bucket(date(2026, 11, 1), 0.1, 0.2)], next_page="p2"),
            _page([_bucket(date(2026, 11, 2)), _bucket(date(2026, 11, 3), 0.13080438340307526)]),
        ]
        days = await usage.fetch_daily_costs(date(2026, 11, 1), NOW)

        assert days == {
            date(2026, 11, 1): Decimal("0.3"),
            date(2026, 11, 2): Decimal(0),
            date(2026, 11, 3): Decimal("0.13080438340307526"),
        }
        first, second = (c.kwargs["params"] for c in http.get.call_args_list)
        assert first["start_time"] == _ts(date(2026, 11, 1))
        assert first["end_time"] == int(NOW.timestamp())
        assert first["bucket_width"] == "1d" and first["limit"] == 180
        assert second["page"] == "p2"
        assert http.get.call_args.kwargs["headers"] == {"Authorization": "Bearer admin-test"}


class TestSync:
    async def test_reads_from_the_first_credit_day_when_it_is_before_the_month(
        self, db_session, http
    ):
        await OpenAIUsageRepository(db_session).add_credit(Decimal("10"), date(2026, 10, 30))
        http.get.return_value = _page([_bucket(date(2026, 10, 30), 1.5)])

        assert await usage.sync(db_session, NOW) is None

        assert http.get.call_args.kwargs["params"]["start_time"] == _ts(date(2026, 10, 30))
        state = await AppSettingRepository(db_session).get(usage.SYNC_KEY)
        assert state == {"at": NOW.isoformat(), "error": None}

    async def test_a_failure_keeps_the_last_update_and_shows_the_error(self, db_session, http):
        await AppSettingRepository(db_session).set(usage.SYNC_KEY, {"at": "earlier", "error": None})
        http.get.return_value = httpx.Response(
            401,
            json={"error": {"message": "Invalid admin key"}},
            request=httpx.Request("GET", usage.COSTS_URL),
        )

        error = await usage.sync(db_session, NOW)

        assert error == "OpenAI 401: Invalid admin key"
        state = await AppSettingRepository(db_session).get(usage.SYNC_KEY)
        assert state == {"at": "earlier", "error": error}


class TestSummary:
    async def test_month_spend_credits_and_remaining(self, db_session):
        repo = OpenAIUsageRepository(db_session)
        await repo.add_credit(Decimal("20.00"), date(2026, 10, 31))
        await repo.add_credit(Decimal("5.00"), date(2026, 11, 5))
        await repo.store_days(
            {
                date(2026, 10, 30): Decimal("9"),  # before the first credit: not deducted
                date(2026, 10, 31): Decimal("1.004"),
                date(2026, 11, 1): Decimal("0.333"),
                date(2026, 11, 10): Decimal("0.338"),
            },
            NOW,
        )

        result = await usage.summary(db_session, NOW)

        assert result["month_start"] == date(2026, 11, 1)
        assert result["month_spend_usd"] == 0.67  # 0.671 summed first, then rounded
        assert result["credits_total_usd"] == 25.0
        assert result["first_credit_on"] == date(2026, 10, 31)
        assert result["spent_since_first_credit_usd"] == 1.68  # 1.675 -> half up
        assert result["remaining_usd"] == 23.33  # 25 - 1.675 = 23.325 -> half up
        assert result["alert"] is None

    async def test_no_credits_means_no_balance(self, db_session):
        result = await usage.summary(db_session, NOW)
        assert result["remaining_usd"] is None
        assert result["last_sync_at"] is None


class TestScheduler:
    async def test_idle_without_the_admin_key(self, monkeypatch):
        monkeypatch.setattr(usage.settings, "openai_admin_key", "")
        factory = AsyncMock()
        await OpenAIUsageScheduler(factory).tick()
        factory.assert_not_called()

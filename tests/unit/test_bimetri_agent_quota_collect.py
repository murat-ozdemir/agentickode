# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: collecting limits per account across workers, and the probe runner."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.models import WorkspaceServer
from backend.services.bimetri_agent_quota import probe as probe_mod
from backend.services.bimetri_agent_quota import service
from backend.services.bimetri_agent_quota.probe import ProbeResult, probe_server, run_user


def _codex(account_id, used=10, error=None):
    resets_at = int(datetime.now(UTC).timestamp()) + 3600  # always in the future
    limits = {"primary": {"usedPercent": used, "windowDurationMins": 300, "resetsAt": resets_at}}
    section = {"account": {"type": "chatgpt", "email": f"{account_id}@example.com"}}
    section["account_id"] = account_id
    if error:
        section["error"] = error
    else:
        section["limits"] = limits
    return section


async def _servers(db_session, n):
    servers = [WorkspaceServer(name=f"worker-{i}", hostname=f"10.0.0.{i}") for i in range(1, n + 1)]
    db_session.add_all(servers)
    await db_session.commit()
    return servers


async def _collect(db_session, results):
    async def fake_probe(server):
        return results[server.name]

    with patch.object(service, "probe_server", fake_probe):
        await service.collect(db_session)
    return await service.summary(db_session)


class TestCollect:
    async def test_shared_account_shows_once_with_all_its_workers(self, db_session):
        await _servers(db_session, 3)
        shared = ProbeResult("coder", {"codex": _codex("cg-1")})
        summary = await _collect(
            db_session,
            {
                "worker-1": shared,
                "worker-2": shared,
                "worker-3": ProbeResult("coder", {"codex": _codex("cg-2", used=55)}),
            },
        )
        by_email = {a["email"]: a for a in summary["accounts"]}
        assert set(by_email) == {"cg-1@example.com", "cg-2@example.com"}
        assert [w["server_name"] for w in by_email["cg-1@example.com"]["workers"]] == [
            "worker-1",
            "worker-2",
        ]
        assert by_email["cg-2@example.com"]["windows"][0]["used_percent"] == 55.0

    async def test_worker_moves_to_its_new_account(self, db_session):
        await _servers(db_session, 1)
        await _collect(db_session, {"worker-1": ProbeResult("coder", {"codex": _codex("cg-1")})})
        summary = await _collect(
            db_session, {"worker-1": ProbeResult("coder", {"codex": _codex("cg-2")})}
        )
        assert [a["email"] for a in summary["accounts"]] == ["cg-2@example.com"]

    async def test_unreachable_server_keeps_its_account_and_reports_the_error(self, db_session):
        await _servers(db_session, 1)
        await _collect(db_session, {"worker-1": ProbeResult("coder", {"codex": _codex("cg-1")})})
        down = ProbeResult("coder", error="probe failed: timeout")
        summary = await _collect(db_session, {"worker-1": down})
        assert [a["email"] for a in summary["accounts"]] == ["cg-1@example.com"]
        assert summary["errors"] == [{"server_name": "worker-1", "error": "probe failed: timeout"}]

    async def test_failed_read_keeps_last_numbers_unless_another_worker_read_it(self, db_session):
        await _servers(db_session, 2)
        await _collect(
            db_session,
            {
                "worker-1": ProbeResult("coder", {"codex": _codex("cg-1", used=40)}),
                "worker-2": ProbeResult("coder", {"codex": _codex("cg-1", error="HTTP 401")}),
            },
        )
        account = (await service.summary(db_session))["accounts"][0]
        assert account["error"] is None and account["windows"][0]["used_percent"] == 40.0

        failing = ProbeResult("coder", {"codex": _codex("cg-1", error="HTTP 401")})
        summary = await _collect(db_session, {"worker-1": failing, "worker-2": failing})
        account = summary["accounts"][0]
        assert account["error"] == "HTTP 401" and account["windows"][0]["used_percent"] == 40.0

    async def test_claude_credits_are_stored_and_returned(self, db_session):
        await _servers(db_session, 1)
        usd = {"amount_minor": 1240, "currency": "USD", "exponent": 2}
        usage = {
            "five_hour": {"utilization": 100.0},
            "seven_day": {"utilization": 9.0},
            "spend": {"enabled": True, "used": usd},
        }
        claude = {"account": {"accountUuid": "acc-1"}, "usage": usage}
        summary = await _collect(db_session, {"worker-1": ProbeResult("coder", {"claude": claude})})
        [account] = summary["accounts"]
        assert account["credits"]["used"] == 12.4 and account["credits"]["enabled"] is True
        assert account["limit_reached"] is True

    async def test_unknown_provider_section_is_ignored(self, db_session):
        await _servers(db_session, 1)
        summary = await _collect(db_session, {"worker-1": ProbeResult("coder", {"other": {}})})
        assert summary["accounts"] == []


def _server(**kw):
    base = {
        "server_type": "remote",
        "worker_user": "coder",
        "worker_user_status": "ready",
        "username": "root",
    }
    return SimpleNamespace(**{**base, **kw})


class TestRunUser:
    @pytest.mark.parametrize(
        ("kw", "expected"),
        [
            ({}, "coder"),
            ({"worker_user_status": "pending"}, None),
            ({"username": "ubuntu"}, None),
            ({"server_type": "local"}, "coder"),
            ({"server_type": "local", "worker_user": "root"}, None),
        ],
    )
    def test_mirrors_the_adapter_factory(self, kw, expected):
        assert run_user(_server(**kw)) == expected


class TestProbeServer:
    async def _run(self, reply=None, raises=None):
        executor = SimpleNamespace(username="root", run_command=AsyncMock(return_value=reply))
        if raises:
            executor.run_command.side_effect = raises
        with patch.object(probe_mod, "executor_for_server", return_value=executor):
            result = await probe_server(_server(name="w"))
        return result, executor

    async def test_runs_the_script_as_the_worker_user_via_stdin(self):
        result, executor = await self._run(('noise\n{"codex": {"account_id": "x"}}\n', "", 0))
        cmd = executor.run_command.call_args.args[0]
        assert cmd.startswith("runuser -l coder -c") and "python3 -" in cmd
        assert "def main" in executor.run_command.call_args.kwargs["input"]
        assert result.user == "coder" and result.sections == {"codex": {"account_id": "x"}}

    async def test_reports_failures(self):
        assert "exit" in ((await self._run(("", "", 2)))[0].error or "")
        assert (await self._run(("not json", "", 0)))[0].error == "probe printed no JSON"
        assert "boom" in ((await self._run(raises=OSError("boom")))[0].error or "")


class TestCurrentWindows:
    def _account(self, resets_at, limit_reached=True):
        window = {"key": "five_hour", "used_percent": 100.0, "resets_at": resets_at}
        return SimpleNamespace(windows=[window], limit_reached=limit_reached)

    def test_window_past_its_reset_time_shows_empty(self):
        now = datetime(2026, 11, 22, 0, 0, tzinfo=UTC)
        windows, hit = service.current_windows(self._account("2026-11-21T22:20:00+00:00"), now)
        assert windows[0]["used_percent"] == 0.0 and windows[0]["resets_at"] is None
        assert hit is False

    def test_full_model_window_after_a_reset_does_not_hit_the_account(self):
        now = datetime(2026, 11, 22, 0, 0, tzinfo=UTC)
        account = self._account("2026-11-21T22:20:00+00:00")
        account.windows.append({"key": "scope_fable", "used_percent": 100.0, "scope": "Fable"})
        _, hit = service.current_windows(account, now)
        assert hit is False

    def test_window_before_its_reset_keeps_the_reading(self):
        now = datetime(2026, 11, 21, 21, 0, tzinfo=UTC)
        windows, hit = service.current_windows(self._account("2026-11-21T22:20:00+00:00"), now)
        assert windows[0]["used_percent"] == 100.0 and hit is True

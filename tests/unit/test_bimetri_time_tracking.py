# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: agent and CI time go to Gitea's time tracker."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from backend.worker.phases._bimetri_time_tracking import (
    add_time,
    ci_span,
    parse_time,
    record_ci_time,
    record_run_time,
    run_time_entry,
)
from tests.unit.bimetri_sahte import SahteGitea

RP = "org/repo"
SHA = "abc12345ff"
T0 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 20, 10, 25, tzinfo=UTC)


def _gitea(times: list | None = None) -> SahteGitea:
    gp = SahteGitea()
    for n in (5, 12):
        gp.yanitlar[f"/repos/{RP}/issues/{n}/times"] = (200, list(times or []))
    return gp


def _run(**kw):
    base = {
        "id": 1,
        "git_provider": "gitea",
        "started_at": T0,
        "completed_at": T1,
        "repo_owner": "org",
        "repo_name": "repo",
        "task_source_meta": {"issue_number": 5, "repo_full_name": RP},
    }
    return SimpleNamespace(**{**base, **kw})


class TestRunTimeEntry:
    def test_issue_run_covers_start_to_end(self):
        assert run_time_entry(_run()) == (RP, 5, 1500.0, T1)

    def test_pr_without_issue_goes_to_pr(self):
        run = _run(task_source_meta={"pr_number": 12})
        assert run_time_entry(run)[:2] == (RP, 12)

    def test_cancelled_run_without_end_counts_until_now(self):
        now = datetime(2026, 11, 20, 10, 5, tzinfo=UTC)
        assert run_time_entry(_run(completed_at=None), now)[2] == 300.0

    def test_naive_db_times_are_utc(self):
        run = _run(started_at=T0.replace(tzinfo=None), completed_at=T1.replace(tzinfo=None))
        assert run_time_entry(run)[2] == 1500.0

    def test_skips_unstarted_or_non_gitea_runs(self):
        assert run_time_entry(_run(started_at=None)) is None
        assert run_time_entry(_run(git_provider="github")) is None
        assert run_time_entry(_run(task_source_meta={})) is None


class TestAddTime:
    async def test_entry_goes_under_the_token_user(self):
        gp = _gitea()
        assert await add_time(gp, RP, 5, 90.7, T1, "agentickode")
        assert gp.dispatch == [
            (f"/repos/{RP}/issues/5/times", {"time": 90, "created": "2026-11-20T10:25:00Z"})
        ]

    async def test_same_user_and_end_is_not_written_twice(self):
        old = {"user_name": "agentickode", "created": "2026-11-20T13:25:00+03:00", "time": 90}
        gp = _gitea([old])
        assert not await add_time(gp, RP, 5, 90, T1, "agentickode")
        assert gp.dispatch == []

    async def test_refused_entry_returns_false(self):
        gp = _gitea()

        async def post(url, json=None, **_kw):
            return SimpleNamespace(status_code=403)

        gp._client.post = post
        assert not await add_time(gp, RP, 5, 60, T1, "agentickode")

    async def test_zero_seconds_writes_nothing(self):
        gp = _gitea()
        assert not await add_time(gp, RP, 5, 0.4, T1, "agentickode")


class TestRecordRunTime:
    async def test_writes_agent_time_under_bot(self):
        gp = _gitea()
        with (
            patch("backend.services.git.get_git_provider", return_value=gp),
            patch("backend.worker.phases._helpers.get_project_token", return_value="t"),
        ):
            await record_run_time(_run(), None)
        assert gp.dispatch[0][1]["time"] == 1500

    async def test_never_raises(self):
        with patch("backend.services.git.get_git_provider", side_effect=RuntimeError("down")):
            await record_run_time(_run(), None)


class TestRecordCiTime:
    def _ci(self, body: str = "Closes #5") -> SahteGitea:
        gp = _gitea()
        gp.yanitlar[f"/repos/{RP}/pulls"] = (
            200,
            [{"number": 12, "body": body, "head": {"sha": SHA}}],
        )
        gp.yanitlar[f"/repos/{RP}/actions/runs"] = (
            200,
            {
                "workflow_runs": [
                    {"id": 3, "path": "dev.yml@x", "created_at": "2026-11-20T09:00:00Z"},
                    {"id": 4, "path": "dev.yml@x", "created_at": "2026-11-20T10:00:00Z"},
                    {"id": 9, "path": "other.yml@x", "created_at": "2026-11-20T10:20:00Z"},
                ]
            },
        )
        return gp

    async def test_latest_dev_run_until_status_time_on_closed_issue(self):
        gp = self._ci()
        out = await record_ci_time(gp, RP, SHA, T1)
        assert out == "#5: CI time written"
        assert gp.dispatch == [
            (f"/repos/{RP}/issues/5/times", {"time": 1500, "created": "2026-11-20T10:25:00Z"})
        ]

    async def test_pr_without_issue_gets_the_time(self):
        gp = self._ci(body="no link")
        assert (await record_ci_time(gp, RP, SHA, T1)).startswith("#12")

    async def test_no_run_writes_nothing(self):
        gp = self._ci()
        gp.yanitlar[f"/repos/{RP}/actions/runs"] = (200, {"workflow_runs": []})
        assert await record_ci_time(gp, RP, SHA, T1) == "no CI run"
        assert gp.dispatch == []


def test_ci_span_uses_run_end_when_no_override():
    run = {"created_at": "2026-11-20T10:00:00Z", "updated_at": "2026-11-20T10:03:00+00:00"}
    start, end = ci_span(run)
    assert (end - start).total_seconds() == 180


def test_parse_time_rejects_garbage():
    assert parse_time("not a date") is None
    assert parse_time("2026-11-20T13:25:00+03:00") == T1

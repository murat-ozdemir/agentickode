# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: human time on a request is estimated from traces at merge, under the bot."""

from datetime import UTC, datetime, timedelta

from backend.worker.phases._bimetri_human_time import (
    estimate_human_seconds,
    record_human_time,
    run_ends,
)
from tests.unit.bimetri_sahte import SahteGitea

RP = "org/repo"
T = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def m(minutes: float) -> datetime:
    return T + timedelta(minutes=minutes)


class TestEstimate:
    def test_comment_counts_from_last_handoff(self):
        out = estimate_human_seconds([(m(30), "murat", "comment")], [m(10)], T)
        assert out == {"murat": 1200}

    def test_content_trace_is_capped_at_an_hour(self):
        out = estimate_human_seconds([(m(600), "murat", "review")], [m(10)], T)
        assert out == {"murat": 3600}

    def test_bare_trace_is_capped_at_ten_minutes(self):
        out = estimate_human_seconds([(m(120), "murat", "merge_pull")], [m(10)], T)
        assert out == {"murat": 600}

    def test_own_previous_trace_starts_the_next_window(self):
        events = [
            (m(20), "murat", "comment"),
            (m(25), "murat", "merge_pull"),
            (m(25), "murat", "close"),
        ]
        assert estimate_human_seconds(events, [m(10)], T) == {"murat": 900}

    def test_bot_reaction_in_the_same_second_is_not_a_handoff(self):
        out = estimate_human_seconds([(m(20), "murat", "label")], [m(10), m(20)], T)
        assert out == {"murat": 600}

    def test_people_are_counted_apart(self):
        events = [(m(20), "murat", "comment"), (m(22), "ayse", "comment")]
        assert estimate_human_seconds(events, [m(10)], T) == {"murat": 600, "ayse": 720}

    def test_trace_without_any_earlier_mark_is_not_counted(self):
        assert estimate_human_seconds([(m(5), "murat", "comment")], [], None) == {}


def _gitea(times: list | None = None) -> SahteGitea:
    gp = SahteGitea()
    gp.yanitlar[f"/repos/{RP}/issues/5"] = (200, {"created_at": "2026-11-20T09:00:00Z"})
    gp.yanitlar[f"/repos/{RP}/issues/12"] = (200, {"created_at": "2026-11-20T09:40:00Z"})
    gp.yanitlar[f"/repos/{RP}/issues/5/timeline"] = (
        200,
        [
            {
                "type": "label",
                "created_at": "2026-11-20T09:00:01Z",
                "user": {"login": "agentickode"},
            },
            {"type": "comment", "created_at": "2026-11-20T09:20:00Z", "user": {"login": "ayse"}},
            {"type": "close", "created_at": "2026-11-20T11:00:00Z", "user": {"login": "murat"}},
        ],
    )
    gp.yanitlar[f"/repos/{RP}/issues/12/timeline"] = (
        200,
        [
            {"type": "review", "created_at": "2026-11-20T10:50:00Z", "user": {"login": "murat"}},
            {
                "type": "merge_pull",
                "created_at": "2026-11-20T11:00:00Z",
                "user": {"login": "murat"},
            },
            {"type": "stop_tracking", "created_at": "2026-11-20T10:55:00Z", "user": {"login": "x"}},
        ],
    )
    gp.yanitlar[f"/repos/{RP}/actions/runs"] = (
        200,
        {
            "workflow_runs": [
                {
                    "id": 4,
                    "path": "dev.yml@x",
                    "status": "completed",
                    "created_at": "2026-11-20T10:30:00Z",
                    "updated_at": "2026-11-20T10:40:00Z",
                }
            ]
        },
    )
    for n in (5, 12):
        gp.yanitlar[f"/repos/{RP}/issues/{n}/times"] = (200, list(times or []))
    return gp


PR = {"number": 12, "head": {"ref": "feature/5-x"}, "merged_at": "2026-11-20T11:00:00Z"}


class TestRecordHumanTime:
    async def test_writes_one_bot_entry_with_everyone_on_the_issue(self, db_session):
        gp = _gitea()
        counted = await record_human_time(gp, db_session, "proj-1", RP, 5, PR)
        # ayse: 09:00:01 bot → 09:20 comment; murat: CI end 10:40 → review 10:50, then merge
        assert counted == {"ayse": 1199, "murat": 1200}
        assert gp.dispatch == [
            (f"/repos/{RP}/issues/5/times", {"time": 2399, "created": "2026-11-20T11:00:00Z"})
        ]

    async def test_person_with_own_record_is_skipped(self, db_session):
        gp = _gitea([{"user_name": "murat", "created": "2026-11-20T10:00:00Z", "time": 300}])
        counted = await record_human_time(gp, db_session, "proj-1", RP, 5, PR)
        assert counted == {"ayse": 1199}
        assert gp.dispatch[0][1]["time"] == 1199

    async def test_redelivered_merge_writes_nothing(self, db_session):
        old = {"user_name": "agentickode", "created": "2026-11-20T11:00:00Z", "time": 2399}
        gp = _gitea([old])
        assert await record_human_time(gp, db_session, "proj-1", RP, 5, PR) == {}
        assert gp.dispatch == []


class TestRunEnds:
    async def test_finds_issue_review_test_and_fix_runs(
        self, db_session, make_task_run, seed_proj1
    ):
        end = datetime(2026, 11, 20, 10, 0)
        for tid in ("5", "pr-12", "pr-test-12", "pr-comment-12-99", "pr-13", "6"):
            db_session.add(make_task_run(task_id=tid, completed_at=end))
        await db_session.commit()
        ends = await run_ends(db_session, "proj-1", 5, 12)
        assert len(ends) == 4 and ends[0].tzinfo is not None

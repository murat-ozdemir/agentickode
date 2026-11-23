# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: the next attempt of the same task gets the previous agent call's summary."""

from unittest.mock import AsyncMock

from backend.models import AgentInvocation
from backend.worker.flow._bimetri_previous_run import SECTION_CHARS, previous_run_section


async def _invocation(db, run, **fields) -> None:
    defaults = {"agent_name": "claude", "phase_name": "implement", "status": "failed"}
    db.add(AgentInvocation(run_id=run.id, **(defaults | fields)))
    await db.commit()


class TestPreviousRunSection:
    async def test_empty_without_an_earlier_call(self, db_session, make_task_run, seed_proj1):
        run = make_task_run(task_id="7")
        db_session.add(run)
        await db_session.commit()
        assert await previous_run_section(db_session, run) == ""

    async def test_a_restart_sees_its_own_earlier_call(self, db_session, make_task_run, seed_proj1):
        run = make_task_run(task_id="7")
        db_session.add(run)
        await db_session.commit()
        await _invocation(
            db_session,
            run,
            files_changed=["src/A.java", "src/B.java"],
            error_message="timeout after 3600s",
            metadata_={"last_message": "Servisi değiştirdim, test kaldı."},
        )
        text = await previous_run_section(db_session, run)
        assert f"koşu #{run.id}" in text
        assert "src/A.java, src/B.java" in text
        assert "Hata: timeout after 3600s" in text
        assert "Servisi değiştirdim, test kaldı." in text

    async def test_a_follow_up_run_sees_the_earlier_runs_error(
        self, db_session, make_task_run, seed_proj1
    ):
        old = make_task_run(task_id="7", error_message="mvn test failed")
        other = make_task_run(task_id="8")
        new = make_task_run(task_id="7")
        db_session.add_all([old, other, new])
        await db_session.commit()
        await _invocation(db_session, old, files_changed=["a.py"])
        await _invocation(db_session, other, files_changed=["other.py"])
        text = await previous_run_section(db_session, new)
        assert f"koşu #{old.id}" in text
        assert "a.py" in text and "other.py" not in text
        assert "Hata: mvn test failed" in text

    async def test_stays_within_the_limit(self, db_session, make_task_run, seed_proj1):
        run = make_task_run(task_id="7")
        db_session.add(run)
        await db_session.commit()
        files = [f"src/F{i}.java" for i in range(40)]
        await _invocation(
            db_session, run, files_changed=files, metadata_={"last_message": "x" * 5000}
        )
        text = await previous_run_section(db_session, run)
        assert len(text) <= SECTION_CHARS
        assert "(+25)" in text

    async def test_a_failing_query_gives_nothing(self, make_task_run):
        session = AsyncMock()
        session.execute.side_effect = RuntimeError("db down")
        assert await previous_run_section(session, make_task_run()) == ""

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 7): what runs and webhooks write to the notebook."""

from backend.worker.phases._bimetri_notebook import load
from backend.worker.phases._bimetri_notebook_record import (
    notebook_prompt,
    record_answer,
    record_ci,
    record_run,
    run_entries,
    run_pr_number,
)
from tests.unit.test_bimetri_notebook import REPORT


def _run(make_task_run, **kw):
    run = make_task_run(**kw)
    run.id = kw.get("id", 9)
    return run


class TestRunEntries:
    def test_test_run_adds_decisions_question_and_record(self, make_task_run):
        run = _run(
            make_task_run,
            task_source_meta={"review_mode": "test", "pr_number": 5},
            coding_results={"response": REPORT, "test_outcome": "Testler geçti"},
        )

        kinds = [(e["kind"], e["text"].splitlines()[0]) for e in run_entries(run)]

        assert kinds == [
            ("decision", "`aufnr` alanı boşsa 400 döner."),
            ("decision", "Liste tarihe göre sıralanır."),
            ("question", "Hata kodu 404 mü 409 mu?"),
            ("run", "Test: Testler geçti"),
        ]

    def test_failed_run_records_why_it_stopped(self, make_task_run):
        run = _run(make_task_run, status="failed", error_message="PR acilmadi")

        assert run_entries(run)[-1]["text"] == "Kod: durdu: PR acilmadi"

    def test_review_outcome_comes_from_the_result_line(self, make_task_run):
        run = _run(make_task_run, review_result={"summary": "x\n**Sonuç:** Değişiklik gerekli"})

        assert run_entries(run)[-1]["text"] == "İnceleme: Değişiklik gerekli"


class TestPrNumber:
    def test_from_meta_or_opened_pr(self, make_task_run):
        assert run_pr_number(make_task_run(task_source_meta={"pr_number": 4})) == 4
        assert run_pr_number(make_task_run(pr_url="http://g/o/r/pulls/12")) == 12

    def test_none_for_other_providers_and_without_pr(self, make_task_run):
        assert run_pr_number(make_task_run(git_provider="github", pr_url="x/pulls/1")) is None
        assert run_pr_number(make_task_run()) is None


class TestRecording:
    async def test_run_answer_and_ci_land_in_the_same_notebook(self, db_session, make_task_run):
        run = _run(
            make_task_run, pr_url="http://g/o/r/pulls/5", coding_results={"response": REPORT}
        )

        await record_run(db_session, run)
        await record_answer(db_session, "proj-1", 5, "mozdemir", "409 dön")
        await record_ci(db_session, "proj-1", 5, "abcdef1234", False)

        row = await load(db_session, "proj-1", 5)
        assert [e["kind"] for e in row.entries][-2:] == ["answer", "ci"]
        assert row.entries[-1]["text"] == "kaldı (`abcdef12`)"

    async def test_run_without_pr_writes_nothing(self, db_session, make_task_run):
        await record_run(db_session, _run(make_task_run))

        assert await load(db_session, "proj-1", 5) is None


class TestPrompt:
    async def test_rules_only_without_notebook(self, db_session, make_task_run):
        text = await notebook_prompt(db_session, make_task_run())

        assert "### Defter" in text and "Zincir defteri (PR" not in text

    async def test_includes_the_prs_notebook(self, db_session, make_task_run):
        await record_answer(db_session, "proj-1", 5, "mozdemir", "409 dön")

        text = await notebook_prompt(db_session, make_task_run(task_source_meta={"pr_number": 5}))

        assert "## Zincir defteri (PR #5" in text
        assert "- **Yanıt:** mozdemir: 409 dön" in text

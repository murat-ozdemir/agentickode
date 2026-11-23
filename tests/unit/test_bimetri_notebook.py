# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 7): the chain notebook of a PR."""

from backend.worker.phases import _bimetri_notebook as nb
from backend.worker.phases._bimetri_notebook import (
    add_entries,
    entry,
    load,
    merge,
    notebook_block,
    prune,
    render,
    split_block,
)

REPORT = (
    "Özet: alan eklendi.\n\n"
    "### Açık soru\nHata kodu 404 mü 409 mu?\n\n"
    "### Defter\n"
    "- Karar: `aufnr` alanı boşsa 400 döner.\n"
    "- **Karar:** Liste tarihe göre sıralanır.\n"
    "- Açık: log seviyesi belirsiz.\n"
    "- Dosyalar: A.java, B.java\n\n"
    "**Sonuç:** Testler geçti"
)


class TestParse:
    def test_block_ends_at_the_result_line(self):
        block = notebook_block(REPORT)

        assert block.startswith("- Karar: `aufnr`")
        assert "Sonuç" not in block

    def test_no_block_is_none(self):
        assert notebook_block("Özet\n\n**Sonuç:** Testler geçti") is None

    def test_splits_decisions_from_the_rest(self):
        decisions, rest = split_block(notebook_block(REPORT))

        assert decisions == ["`aufnr` alanı boşsa 400 döner.", "Liste tarihe göre sıralanır."]
        assert rest == "- Açık: log seviyesi belirsiz.\n- Dosyalar: A.java, B.java"


class TestMerge:
    def test_permanent_entries_are_not_repeated(self):
        first = merge([], [entry("decision", "a")])

        assert len(merge(first, [entry("decision", "a"), entry("answer", "a")])) == 2

    def test_a_runs_record_replaces_its_earlier_one(self):
        entries = merge([], [entry("run", "Kod: durdu", 7)])

        entries = merge(entries, [entry("run", "Kod: tamamlandı", 7)])

        assert [e["text"] for e in entries] == ["Kod: tamamlandı"]

    def test_keeps_last_records_and_all_decisions(self):
        entries = [entry("decision", f"k{i}") for i in range(3)]
        entries += [entry("run", f"r{i}", i + 1) for i in range(8)]

        kept = prune(entries)

        assert [e["text"] for e in kept if e["kind"] == "decision"] == ["k0", "k1", "k2"]
        assert [e["text"] for e in kept if e["kind"] == "run"] == [f"r{i}" for i in range(3, 8)]

    def test_drops_oldest_records_over_the_size_limit(self, monkeypatch):
        monkeypatch.setattr(nb, "MAX_CHARS", 100)
        entries = [entry("decision", "k" * 50), entry("ci", "x" * 30), entry("run", "y" * 10, 1)]

        kept = prune(entries)

        assert [e["kind"] for e in kept] == ["decision", "run"]


def test_render_labels_entries():
    text = render([entry("decision", "a", 3), entry("ci", "geçti (`abc`)")])

    assert text == "- **Karar #3:** a\n- **CI:** geçti (`abc`)"


class TestStore:
    async def test_creates_then_updates_the_prs_notebook(self, db_session):
        await add_entries(db_session, "proj-1", 5, [entry("decision", "a")])
        await add_entries(db_session, "proj-1", 5, [entry("answer", "mozdemir: 409")])

        row = await load(db_session, "proj-1", 5)

        assert [e["kind"] for e in row.entries] == ["decision", "answer"]
        assert await load(db_session, "proj-1", 6) is None

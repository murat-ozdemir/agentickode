# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 2): graph_read and use-site statements over the clone."""

import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _graph_read as reader  # noqa: E402

SVC = "core/src/ResourceStatusService.java"
JAVA = """package x;

public class ResourceStatusService {
    /* a { brace in a comment,
     * and void update(int x) in a Javadoc */
    private final String s = "}";

    public void update(String id) {
        if (id != null) {
            save(id);
        }
    }

    abstract void close();

    void other() { return update("a"); }
}
"""


@pytest.fixture
def root(tmp_path):
    (tmp_path / "core/src").mkdir(parents=True)
    (tmp_path / SVC).write_text(JAVA)
    return tmp_path


class TestSymbol:
    def test_symbol_reads_only_its_block(self, root):
        text = reader.read(root, f"{SVC}::update")
        assert text.splitlines()[0] == f"{SVC}:8-12"
        assert text.splitlines()[-1] == "12:     }"

    def test_declarations_skip_calls_and_comments(self):
        lines = JAVA.splitlines()
        assert [lines[i].strip()[:20] for i in reader.declarations(lines, "update")] == [
            "public void update(S"
        ]

    def test_body_less_declaration_ends_at_its_semicolon(self, root):
        assert reader.read(root, f"{SVC}::close").splitlines()[0] == f"{SVC}:14-14"

    def test_class_block_ignores_braces_in_strings_and_comments(self, root):
        text = reader.read(root, f"{SVC}::ResourceStatusService")
        assert text.splitlines()[0] == f"{SVC}:3-17"


class TestFileAndLines:
    def test_whole_file_is_capped(self, root, monkeypatch):
        monkeypatch.setattr(reader, "FILE_LINES", 2)
        assert reader.read(root, SVC).splitlines() == [
            "1: package x;",
            "2: ",
            "... 15 more lines; read a symbol with file::Name",
        ]

    def test_line_reads_a_window_around_it(self, root, monkeypatch):
        monkeypatch.setattr(reader, "WINDOW_LINES", 1)
        assert reader.read(root, f"{SVC}:10").splitlines() == [
            f"{SVC}:9-11",
            "9:         if (id != null) {",
            "10:             save(id);",
            "11:         }",
        ]
        assert reader.read(root, f"{SVC}:1").splitlines()[0] == f"{SVC}:1-2"

    def test_range_reads_those_lines(self, root):
        assert reader.read(root, f"{SVC}:14-16").splitlines()[0] == f"{SVC}:14-16"
        assert reader.read(root, f"{SVC}:99") == f"{SVC} has 17 lines"

    def test_stays_inside_the_clone(self, root):
        assert reader.read(root, "../etc/passwd").startswith("no such file")
        assert reader.read(root, "../etc/passwd:3").startswith("no such file")
        assert "not declared" in reader.read(root, f"{SVC}::missing")


class TestStatement:
    def test_joins_lines_until_the_parentheses_close(self):
        lines = ["call(a,", '  b, ")",', "  c);", "next();"]
        assert reader.statement(lines, 1) == 'call(a, b, ")", c);'
        assert reader.statement(lines, 4) == "next();"
        assert reader.statement(lines, 9) == ""

    def test_long_statements_are_cut(self, monkeypatch):
        monkeypatch.setattr(reader, "USE_WIDTH", 10)
        assert reader.statement(["x" * 20], 1) == "xxxxxxx..."

    def test_sources_read_each_file_once_and_stay_in_the_clone(self, root):
        sources = reader.Sources(root)
        assert sources.at(SVC, 10) == "save(id);"
        assert list(sources.files) == [SVC]
        assert sources.at("../x.java", 1) == "" and reader.Sources(None).at(SVC, 10) == ""

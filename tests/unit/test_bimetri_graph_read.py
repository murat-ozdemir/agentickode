# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 2, Faz 1): graph_read and use-site statements over the clone."""

import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _graph_read as reader  # noqa: E402
import _graph_reply as reply  # noqa: E402

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
        text = reply.read(root, f"{SVC}::update")
        assert text.splitlines()[0] == f"{SVC}:8-12"
        assert text.splitlines()[-1] == "12:     }"

    def test_declarations_skip_calls_and_comments(self):
        lines = JAVA.splitlines()
        assert [lines[i].strip()[:20] for i in reader.declarations(lines, "update")] == [
            "public void update(S"
        ]

    def test_body_less_declaration_ends_at_its_semicolon(self, root):
        assert reply.read(root, f"{SVC}::close").splitlines()[0] == f"{SVC}:14-14"

    def test_class_block_ignores_braces_in_strings_and_comments(self, root):
        text = reply.read(root, f"{SVC}::ResourceStatusService")
        assert text.splitlines()[0] == f"{SVC}:3-17"


class TestFileAndLines:
    def test_small_file_comes_whole(self, root):
        part = reply.read_part(root, SVC)
        assert part.text.splitlines()[:2] == ["1: package x;", "2: "]
        assert part.ranges == [(1, 17)] and part.stamp[1] == len(JAVA)

    def test_large_file_comes_as_an_outline(self, root, monkeypatch):
        monkeypatch.setattr(reply, "READ_CHARS", 350)
        part = reply.read_part(root, SVC)
        assert part.ranges == []
        assert part.text.splitlines() == [
            f"{SVC}: 17 lines, outline; read code with {SVC}::Name or {SVC}:START-END",
            "3-17: public class ResourceStatusService",
            "8-12: public void update(String id)",
            "14-14: abstract void close();",
            '16-16: void other() { return update("a"); }',
        ]

    def test_outline_is_capped_too(self, root, monkeypatch):
        head = f"{SVC}: 17 lines, outline; read code with {SVC}::Name or {SVC}:START-END"
        monkeypatch.setattr(reply, "READ_CHARS", len(head) + 80)
        text = reply.read(root, SVC)
        assert text.splitlines()[-2:] == [
            "8-12: public void update(String id)",
            "... 2 more declarations",
        ]

    def test_python_outline_uses_indentation(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reply, "READ_CHARS", 200)
        body = "        return text  # " + "x" * 200
        code = f"class Ledger:\n    def send(self, text):\n{body}\n\n\ndef free():\n    pass\n"
        (tmp_path / "a.py").write_text(code)
        assert reply.read(tmp_path, "a.py").splitlines()[1:] == [
            "1-3: class Ledger:",
            "2-3: def send(self, text):",
            "6-7: def free():",
        ]
        assert reply.read(tmp_path, "a.py::send").splitlines()[0] == "a.py:2-3"

    def test_long_reads_are_cut_with_the_next_range(self, root, monkeypatch):
        monkeypatch.setattr(reply, "READ_CHARS", 60)
        part = reply.read_part(root, f"{SVC}:1-17")
        assert part.text.splitlines()[-1] == f"... cut at 60 chars; read {SVC}:4-17 next"
        assert part.ranges == [(1, 3)]

    def test_line_reads_a_window_around_it(self, root, monkeypatch):
        monkeypatch.setattr(reply, "WINDOW_LINES", 1)
        assert reply.read(root, f"{SVC}:10").splitlines() == [
            f"{SVC}:9-11",
            "9:         if (id != null) {",
            "10:             save(id);",
            "11:         }",
        ]
        assert reply.read(root, f"{SVC}:1").splitlines()[0] == f"{SVC}:1-2"

    def test_range_reads_those_lines(self, root):
        assert reply.read(root, f"{SVC}:14-16").splitlines()[0] == f"{SVC}:14-16"
        assert reply.read(root, f"{SVC}:99") == f"{SVC} has 17 lines"

    def test_stays_inside_the_clone(self, root):
        assert reply.read(root, "../etc/passwd").startswith("no such file")
        assert reply.read(root, "../etc/passwd:3").startswith("no such file")
        assert "not declared" in reply.read(root, f"{SVC}::missing")


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

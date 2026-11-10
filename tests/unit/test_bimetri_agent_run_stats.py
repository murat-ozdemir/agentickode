# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 phase 1): tool and token counts of a run from its Claude transcript."""

import json
import subprocess
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _agent_run_stats as stats  # noqa: E402


def prompt(text, stamp="2026-11-10T10:00:00.000Z"):
    return {"type": "user", "timestamp": stamp, "message": {"role": "user", "content": text}}


def reply(msg_id, blocks, stamp, usage=None):
    usage = usage or {
        "input_tokens": 10,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 1000,
        "output_tokens": 5,
    }
    message = {"id": msg_id, "content": blocks, "usage": usage}
    return {"type": "assistant", "timestamp": stamp, "message": message}


def tool(name, **kwargs):
    return {"type": "tool_use", "name": name, "input": kwargs}


def write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in records] + ["not json"]
    path.write_text("\n".join(lines) + "\n")
    return path


def run_prompt(run_id):
    return f"Task...\n## Project memory (mem0)\n`run_id` = {run_id}, search with it."


class TestFindSessions:
    def test_matches_the_exact_run_id(self, tmp_path):
        hit = write(tmp_path / "p" / "a.jsonl", [prompt(run_prompt(74))])
        write(tmp_path / "p" / "b.jsonl", [prompt(run_prompt(740))])
        write(tmp_path / "q" / "c.jsonl", [prompt(run_prompt(7))])
        assert stats.find_sessions(tmp_path, 74) == [hit]

    def test_reads_the_prompt_from_content_blocks(self, tmp_path):
        record = prompt([{"type": "text", "text": run_prompt(9)}])
        hit = write(tmp_path / "p" / "a.jsonl", [record])
        assert stats.find_sessions(tmp_path, 9) == [hit]

    def test_only_the_first_prompt_counts(self, tmp_path):
        write(tmp_path / "p" / "a.jsonl", [prompt("other task"), prompt(run_prompt(9))])
        assert stats.find_sessions(tmp_path, 9) == []

    def test_subagent_transcripts_are_not_sessions(self, tmp_path):
        write(tmp_path / "p" / "s" / "subagents" / "x.jsonl", [prompt(run_prompt(9))])
        assert stats.find_sessions(tmp_path, 9) == []


class TestSummarise:
    def test_counts_tools_and_dedupes_usage_per_response(self, tmp_path):
        path = write(
            tmp_path / "a.jsonl",
            [
                prompt(run_prompt(1)),
                # Same response written as two lines, one per content block.
                reply("m1", [tool("Grep", pattern="x")], "2026-11-10T10:00:02.000Z"),
                reply("m1", [tool("Read", file_path="/a.java")], "2026-11-10T10:00:02.500Z"),
                reply("m2", [tool("mcp__bimetri-graph__query")], "2026-11-10T10:00:10.000Z"),
                reply("m3", [tool("Read", file_path="/a.java")], "2026-11-10T10:00:20.000Z"),
                reply("m4", [{"type": "text", "text": "done"}], "2026-11-10T10:01:00.000Z"),
            ],
        )
        result = stats.summarise([path])
        assert result["responses"] == 4
        assert result["tokens"] == {
            "input": 40,
            "cache write": 400,
            "cache read": 4000,
            "output": 20,
        }
        assert result["tools"] == {"Read": 2, "Grep": 1, "mcp__bimetri-graph__query": 1}
        assert result["graph_calls"] == 1
        assert result["distinct_reads"] == 1
        assert result["duration"] == 60.0

    def test_empty_transcript(self, tmp_path):
        path = write(tmp_path / "a.jsonl", [])
        result = stats.summarise([path])
        assert result["duration"] == 0.0 and result["tools"] == {} and result["responses"] == 0


class TestReport:
    def test_includes_subagent_transcripts(self, tmp_path, capsys):
        main = write(
            tmp_path / "p" / "s.jsonl",
            [prompt(run_prompt(5)), reply("m1", [tool("Agent")], "2026-11-10T10:00:01.000Z")],
        )
        write(
            tmp_path / "p" / "s" / "subagents" / "agent-1.jsonl",
            [reply("m2", [tool("mcp__bimetri-graph__q")], "2026-11-10T10:00:30.000Z")],
        )
        assert stats.report(5, tmp_path) == 0
        out = capsys.readouterr().out
        assert f"run 5: {main} (+1 subagent transcripts)" in out
        assert "duration 30.0s, API responses 2" in out
        assert "graph calls 1" in out

    def test_says_when_this_worker_did_not_run_it(self, tmp_path, capsys):
        assert stats.report(5, tmp_path) == 0
        assert "no Claude transcript on this worker" in capsys.readouterr().out

    def test_main_rejects_a_bad_run_id(self, capsys):
        assert stats.main(["stats", "x"]) == 2
        assert "usage" in capsys.readouterr().err


class TestShellScript:
    script = _DIR / "agent-graph-mcp.sh"

    def run(self, *args):
        return subprocess.run(["bash", str(self.script), *args], capture_output=True, text=True)

    def test_stats_runs_the_stats_program_as_the_worker_user(self):
        done = self.run("--dry-run", "stats", "74", "h1", "h2")
        assert done.returncode == 0
        expected = "runuser -u coder -- python3 -c <scripts/bimetri/_agent_run_stats.py> stats 74"
        assert done.stdout.count(expected) == 2

    def test_stats_needs_a_numeric_run_id(self):
        done = self.run("--dry-run", "stats", "h1")
        assert done.returncode == 2 and "usage" in done.stderr

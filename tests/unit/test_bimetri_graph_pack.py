# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (graf tasarruf planı, Faz 2): the context pack, worker and backend sides."""

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.worker.flow import _bimetri_graph_pack as backend_pack

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "bimetri"
sys.path.insert(0, str(_DIR))

import _graph_budget as budget  # noqa: E402
import _graph_flow_server as server  # noqa: E402
import _graph_pack as pack  # noqa: E402

from tests.unit.test_bimetri_graph_flow import JAVA, SVC, FakeGraph, node  # noqa: E402


@pytest.fixture
def clone(tmp_path):
    (tmp_path / "core/src").mkdir(parents=True)
    (tmp_path / SVC).write_text(JAVA)
    nodes = {
        "svc": node("ResourceStatusService", SVC, 3),
        "upd": node(".update()", SVC, 8),
        "ctl": node(".refresh()", "api/StatusController.java", 20),
    }
    links = [("ctl", "upd", {"relation": "calls", "source_location": "L57"})]
    return FakeGraph(nodes, links), tmp_path


class TestBuild:
    def test_pack_has_the_flow_answer_code_and_callers(self, clone):
        graph, root = clone
        text, sent = pack.build(graph, "ResourceStatusService.update() düzelt", root)
        assert text.startswith("## Kod grafiği bağlam paketi")
        assert f"- {SVC}::update" in text
        assert "8:     public void update(String id) {" in text
        assert "api/StatusController.java:57 .refresh() calls .update()" in text
        assert sent["greps"] == 1 and f"{SVC}::update" in sent["files"]
        assert sent["callers"] == [f"{SVC}::update"]
        assert all(r[0] == SVC for r in sent["ranges"])

    def test_nothing_recommended_is_no_pack(self, clone):
        graph, root = clone
        assert pack.build(graph, "hiçbir ad yok", root)[0] == ""

    def test_bodies_keep_to_the_size_cap(self, clone, monkeypatch):
        graph, root = clone
        monkeypatch.setattr(pack, "PACK_CHARS", 700)
        text, sent = pack.build(graph, "ResourceStatusService.update()", root)
        assert len(text) <= 700 + 200  # the header and list, then no body over the cap
        assert sent["ranges"] == []


class TestSentByThePack:
    def test_the_server_does_not_send_pack_code_again(self, clone):
        graph, root = clone
        _, sent = pack.build(graph, "ResourceStatusService.update()", root)
        pack.save(root / "base", "9", sent)
        assert (root / "base/gate/run-9").read_text() == "1"
        ledger = budget.Ledger()
        assert pack.adopt(ledger, root / "base/pack/9.json") == 1
        flow = server.Flow(root / "graph.json", root, lambda p: graph, lambda g, t: [])
        flow.ledger = ledger
        note = flow.read(f"{SVC}::update")
        assert "already sent in the prompt's context pack" in note
        # Asked again (context compacted), it is served.
        assert "public void update" in flow.read(f"{SVC}::update")

    def test_no_pack_file_leaves_the_budget_unset(self, tmp_path):
        assert pack.adopt(budget.Ledger(), tmp_path / "none.json") is None

    def test_no_run_id_writes_nothing(self, tmp_path):
        pack.save(tmp_path, None, {"greps": 1})
        assert list(tmp_path.iterdir()) == []

    def test_server_pack_prints_and_records(self, clone, capsys):
        graph, root = clone
        (root / "graph.json").write_text("{}")
        flow = server.Flow(root / "graph.json", root, lambda p: graph, lambda g, t: [])
        calls = []
        rc = server.pack(flow, "update()", lambda *a: calls.append(a), root / "b", "5")
        assert rc == 0 and capsys.readouterr().out.startswith("## Kod grafiği")
        assert calls[0][0] == "context_pack" and calls[0][1]["files"]


class TestBackend:
    def test_command_runs_as_the_worker_user_with_the_task_on_stdin(self):
        cmd = backend_pack.pack_command(7, "/ws/run 7", "Görev", "worker")
        assert cmd.startswith("runuser -u worker -- bash -c ")
        assert base64.b64encode("Görev".encode()).decode() in cmd
        assert "BIMETRI_RUN_ID=7" in cmd and "/home/worker/.local/share" in cmd
        assert "'\"'\"'/ws/run 7'\"'\"'" in cmd  # the clone path stays one argument

    async def test_returns_the_pack_section(self):
        ssh = SimpleNamespace(
            username="root", run_command=AsyncMock(return_value=("## P\n", "", 0))
        )
        adapter = SimpleNamespace(_ssh=ssh, _worker_user="w")
        assert await backend_pack.context_pack(adapter, 1, "/ws", "t") == "\n\n## P"

    @pytest.mark.parametrize("answer", [("", "", 0), ("## P", "boom", 1), ("not a pack", "", 0)])
    async def test_anything_else_is_no_pack(self, answer):
        ssh = SimpleNamespace(username="u", run_command=AsyncMock(return_value=answer))
        assert await backend_pack.context_pack(SimpleNamespace(_ssh=ssh), 1, "/ws", "t") == ""

    async def test_ssh_failure_and_missing_clone_are_no_pack(self):
        ssh = SimpleNamespace(username="u", run_command=AsyncMock(side_effect=OSError("x")))
        adapter = SimpleNamespace(_ssh=ssh)
        assert await backend_pack.context_pack(adapter, 1, "/ws", "t") == ""
        assert await backend_pack.context_pack(adapter, 1, None, "t") == ""
        assert await backend_pack.context_pack(object(), 1, "/ws", "t") == ""

    def test_task_text_is_capped(self):
        assert len(backend_pack.task_text("T", "x" * 10_000)) == backend_pack.TASK_CHARS
        assert json.dumps(backend_pack.task_text(None, None)) == '""'

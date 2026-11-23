# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: the quota probe renews an expired Claude login on an idle worker."""

import io
import json
import time

from backend.services.bimetri_agent_quota import worker_probe


def _write(home, expires_at):
    (home / ".claude").mkdir(exist_ok=True)
    creds = {"claudeAiOauth": {"accessToken": f"tok-{expires_at}", "expiresAt": expires_at}}
    (home / ".claude" / ".credentials.json").write_text(json.dumps(creds))


def _idle_worker(tmp_path, monkeypatch, renew_to):
    _write(tmp_path, (time.time() - 60) * 1000)
    monkeypatch.setattr(worker_probe, "HOME", str(tmp_path))
    monkeypatch.setattr(worker_probe, "_claude_running", lambda: False)
    monkeypatch.setattr(worker_probe.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        _write(tmp_path, renew_to)

    monkeypatch.setattr(worker_probe.subprocess, "run", fake_run)
    return calls


class TestRefresh:
    def test_idle_worker_renews_the_login_and_reads_usage(self, tmp_path, monkeypatch):
        fresh = int((time.time() + 3600) * 1000)
        calls = _idle_worker(tmp_path, monkeypatch, fresh)
        seen = {}

        def fake_urlopen(req, timeout):
            seen["auth"] = req.get_header("Authorization")
            return io.StringIO(json.dumps({"five_hour": {"utilization": 2.0}}))

        monkeypatch.setattr(worker_probe.urllib.request, "urlopen", fake_urlopen)
        out = worker_probe.claude()
        assert calls == [worker_probe.REFRESH_CMD]
        assert "--strict-mcp-config" in calls[0] and "haiku" in calls[0]
        assert seen["auth"] == f"Bearer tok-{fresh}"
        assert out["usage"] == {"five_hour": {"utilization": 2.0}} and "error" not in out

    def test_a_call_that_does_not_renew_is_reported(self, tmp_path, monkeypatch):
        _idle_worker(tmp_path, monkeypatch, (time.time() - 30) * 1000)
        monkeypatch.setattr(worker_probe.urllib.request, "urlopen", None)
        out = worker_probe.claude()
        assert out["error"] == "token expired; refresh call did not renew it"

    def test_running_agent_call_is_left_alone(self, tmp_path, monkeypatch):
        calls = _idle_worker(tmp_path, monkeypatch, 0)
        monkeypatch.setattr(worker_probe, "_claude_running", lambda: True)
        assert "agent call is running" in worker_probe.claude()["error"]
        assert calls == []

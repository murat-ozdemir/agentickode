# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: the Codex probe names the account even when account/read comes back empty."""

import json

import pytest

from backend.services.bimetri_agent_quota import worker_probe
from backend.services.bimetri_agent_quota.codex_adapter import CodexQuotaAdapter

LIMITS = {"id": 2, "result": {"rateLimits": {"primary": {"usedPercent": 3}, "planType": "plus"}}}
READ = {
    "id": 1,
    "result": {
        "account": {"type": "chatgpt", "email": "dev@example.com", "planType": "plus"},
        "workspaceRouting": {"chatgptAccountId": "acc-from-read"},
    },
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    (tmp_path / ".codex").mkdir()
    login = {"auth_mode": "chatgpt", "tokens": {"access_token": "secret", "account_id": "acc-1"}}
    (tmp_path / ".codex" / "auth.json").write_text(json.dumps(login))
    monkeypatch.setattr(worker_probe, "HOME", str(tmp_path))
    monkeypatch.setattr(worker_probe.shutil, "which", lambda _: "/usr/bin/codex")
    return tmp_path


def _replies(monkeypatch, *replies):
    monkeypatch.setattr(worker_probe, "_app_server", lambda _: {r["id"]: r for r in replies})


def test_account_read_names_the_account(home, monkeypatch):
    _replies(monkeypatch, READ, LIMITS)
    out = worker_probe.codex()
    assert out["account_id"] == "acc-from-read"
    assert out["account"]["email"] == "dev@example.com"


@pytest.mark.parametrize("read", [None, {"id": 1, "error": {"message": "busy"}}])
def test_empty_account_read_falls_back_to_the_login_file(home, monkeypatch, read):
    _replies(monkeypatch, *([read] if read else []), LIMITS)
    out = worker_probe.codex()
    assert out["account_id"] == "acc-1"
    assert "secret" not in json.dumps(out)
    # same key as the rounds where account/read answered, so no "Unknown account" row
    assert CodexQuotaAdapter().parse(out).account_key == "acc-1"


def test_login_without_tokens_leaves_the_account_unknown(home, monkeypatch):
    (home / ".codex" / "auth.json").write_text(json.dumps({"auth_mode": "apikey"}))
    _replies(monkeypatch, LIMITS)
    assert worker_probe.codex()["account_id"] is None

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Claude / Codex limit parsing and the worker-side probe script."""

import io
import json
import time

from backend.services.bimetri_agent_quota import worker_probe
from backend.services.bimetri_agent_quota.claude_adapter import ClaudeQuotaAdapter
from backend.services.bimetri_agent_quota.codex_adapter import CodexQuotaAdapter

CLAUDE_SECTION = {
    "account": {
        "accountUuid": "acc-1",
        "emailAddress": "dev@example.com",
        "organizationName": "Example",
    },
    "plan": "pro",
    "usage": {
        "five_hour": {"utilization": 100.0, "resets_at": "2026-11-21T22:20:00+00:00"},
        "seven_day": {"utilization": 9.0, "resets_at": "2026-11-28T01:00:00+00:00"},
    },
}

CODEX_LIMITS = {
    "primary": {"usedPercent": 29, "windowDurationMins": 10080, "resetsAt": 1795545554},
    "secondary": {"usedPercent": 100, "windowDurationMins": 300, "resetsAt": 1795300374},
    "planType": "plus",
    "rateLimitReachedType": "rate_limit_reached",
}


class TestClaudeAdapter:
    def test_reads_account_plan_and_both_windows(self):
        r = ClaudeQuotaAdapter().parse(CLAUDE_SECTION)
        assert (r.account_key, r.email, r.plan, r.org_name) == (
            "acc-1",
            "dev@example.com",
            "pro",
            "Example",
        )
        assert [(w.key, w.used_percent) for w in r.windows] == [
            ("five_hour", 100.0),
            ("weekly", 9.0),
        ]
        assert r.windows[0].resets_at == "2026-11-21T22:20:00+00:00"
        assert r.limit_reached is True

    def test_known_account_without_usage_keeps_the_error(self):
        section = {**CLAUDE_SECTION, "usage": None, "error": "usage request failed: HTTP 401"}
        r = ClaudeQuotaAdapter().parse(section)
        assert r.account_key == "acc-1" and r.windows == [] and "401" in (r.error or "")
        assert r.limit_reached is False

    def test_falls_back_to_email_as_the_key(self):
        r = ClaudeQuotaAdapter().parse({"account": {"emailAddress": "x@example.com"}})
        assert r.account_key == "x@example.com"


def _usage(**extra):
    return {**CLAUDE_SECTION, "usage": {**CLAUDE_SECTION["usage"], **extra}}


def _usd(cents):
    return {"amount_minor": cents, "currency": "USD", "exponent": 2}


class TestClaudeCredits:
    def test_off_and_unused_credits_are_left_out(self):
        off = {"enabled": False, "used": _usd(0)}
        r = ClaudeQuotaAdapter().parse(_usage(spend=off, extra_usage={"is_enabled": False}))
        assert r.credits is None

    def test_enabled_credits_report_spend_limit_and_balance(self):
        spend = {"enabled": True, "used": _usd(1240), "limit": _usd(5000), "balance": _usd(3760)}
        r = ClaudeQuotaAdapter().parse(_usage(spend=spend, extra_usage={"is_enabled": True}))
        assert r.credits == {
            "enabled": True,
            "used": 12.4,
            "limit": 50.0,
            "balance": 37.6,
            "currency": "USD",
            "used_percent": 24.8,
            "limit_reached": False,
        }

    def test_falls_back_to_extra_usage_in_minor_units(self):
        extra = {
            "is_enabled": True,
            "used_credits": 5000,
            "decimal_places": 2,
            "utilization": 100,
            "currency": "EUR",
            "spend_limit_reached": True,
        }
        credits = ClaudeQuotaAdapter().parse(_usage(extra_usage=extra)).credits or {}
        assert (credits["used"], credits["currency"], credits["used_percent"]) == (
            50.0,
            "EUR",
            100.0,
        )
        assert credits["limit_reached"] is True and credits["limit"] is None

    def test_unknown_money_shapes_are_not_guessed(self):
        spend = {"enabled": True, "used": 12, "limit": "50"}
        credits = ClaudeQuotaAdapter().parse(_usage(spend=spend)).credits or {}
        assert (credits["used"], credits["limit"], credits["used_percent"]) == (None, None, None)


class TestClaudeScopedLimits:
    def test_model_limit_gets_its_own_bar_but_does_not_hit_the_account(self):
        limits = [
            {"kind": "session", "group": "session", "percent": 40},
            {"kind": "weekly_all", "group": "weekly", "percent": 9},
            {
                "kind": "weekly_model",
                "group": "weekly",
                "percent": 100,
                "scope": "fable",
                "resets_at": "2026-11-28T01:00:00+00:00",
            },
        ]
        usage = {"five_hour": {"utilization": 40.0}, "seven_day": {"utilization": 9.0}}
        r = ClaudeQuotaAdapter().parse({**CLAUDE_SECTION, "usage": {**usage, "limits": limits}})
        assert [(w.key, w.label, w.scope, w.minutes) for w in r.windows[2:]] == [
            ("scope_fable", "Fable", "Fable", 10080)
        ]
        assert r.windows[2].used_percent == 100.0 and r.limit_reached is False

    def test_model_slots_fill_in_and_are_not_doubled(self):
        limits = [{"kind": "weekly_opus", "group": "weekly", "percent": 30}]
        r = ClaudeQuotaAdapter().parse(
            _usage(
                limits=limits,
                seven_day_opus={"utilization": 30.0},
                seven_day_sonnet={"utilization": 12.0},
            )
        )
        assert [(w.label, w.used_percent) for w in r.windows[2:]] == [
            ("Opus", 30.0),
            ("Sonnet", 12.0),
        ]

    def test_scope_object_uses_its_display_name(self):
        limits = [
            {"kind": "x", "group": "other", "percent": 5, "scope": {"display_name": "Fable 5"}}
        ]
        [w] = ClaudeQuotaAdapter().parse(_usage(limits=limits)).windows[2:]
        assert (w.key, w.label, w.minutes) == ("scope_fable_5", "Fable 5", None)


class TestCodexAdapter:
    def test_names_windows_by_length_not_slot(self):
        section = {
            "account": {"type": "chatgpt", "email": "dev@example.com", "planType": "plus"},
            "account_id": "cg-1",
            "limits": CODEX_LIMITS,
        }
        r = CodexQuotaAdapter().parse(section)
        assert (r.account_key, r.email, r.plan) == ("cg-1", "dev@example.com", "plus")
        assert [(w.key, w.label, w.used_percent) for w in r.windows] == [
            ("five_hour", "5h", 100.0),
            ("weekly", "Weekly", 29.0),
        ]
        assert r.windows[0].resets_at and r.windows[0].resets_at.startswith("2026-11-21")
        assert r.limit_reached is True

    def test_missing_secondary_window_is_skipped(self):
        limits = {"primary": {"usedPercent": 12, "windowDurationMins": 300, "resetsAt": 0}}
        r = CodexQuotaAdapter().parse({"account_id": "cg-1", "limits": limits})
        assert [w.key for w in r.windows] == ["five_hour"]
        assert r.windows[0].resets_at is None and r.limit_reached is False

    def test_api_key_login_has_no_plan_limits(self):
        r = CodexQuotaAdapter().parse({"account": {"type": "apiKey"}, "account_id": None})
        assert r.windows == [] and "API key" in (r.error or "")

    def test_unusual_window_length_gets_its_own_key(self):
        limits = {"primary": {"usedPercent": 5, "windowDurationMins": 1440}}
        r = CodexQuotaAdapter().parse({"account_id": "cg-1", "limits": limits})
        assert (r.windows[0].key, r.windows[0].label) == ("window_1440", "24h")


class TestWorkerProbeClaude:
    def _home(self, tmp_path, monkeypatch, expires_at):
        (tmp_path / ".claude").mkdir()
        creds = {
            "claudeAiOauth": {
                "accessToken": "secret-token",
                "expiresAt": expires_at,
                "subscriptionType": "max",
            }
        }
        (tmp_path / ".claude" / ".credentials.json").write_text(json.dumps(creds))
        account = {"oauthAccount": {"accountUuid": "acc-9", "emailAddress": "w@example.com"}}
        (tmp_path / ".claude.json").write_text(json.dumps(account))
        monkeypatch.setattr(worker_probe, "HOME", str(tmp_path))

    def test_prints_usage_without_the_token(self, tmp_path, monkeypatch):
        self._home(tmp_path, monkeypatch, (time.time() + 3600) * 1000)
        body = {
            "five_hour": {"utilization": 3.0},
            "seven_day": {"utilization": 1.0},
            "spend": {"enabled": False},
            "seven_day_opus": None,
            "x": 1,
        }
        seen = {}

        def fake_urlopen(req, timeout):
            seen["auth"] = req.get_header("Authorization")
            return io.StringIO(json.dumps(body))

        monkeypatch.setattr(worker_probe.urllib.request, "urlopen", fake_urlopen)
        out = worker_probe.claude()
        assert seen["auth"] == "Bearer secret-token"
        assert out["usage"] == {k: v for k, v in body.items() if k != "x"}
        assert out["plan"] == "max" and out["account"]["accountUuid"] == "acc-9"
        assert "secret-token" not in json.dumps(out)

    def test_expired_token_is_not_sent(self, tmp_path, monkeypatch):
        self._home(tmp_path, monkeypatch, (time.time() - 60) * 1000)
        monkeypatch.setattr(worker_probe.urllib.request, "urlopen", None)
        out = worker_probe.claude()
        assert "expired" in out["error"] and "usage" not in out

    def test_not_logged_in_reports_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(worker_probe, "HOME", str(tmp_path))
        assert worker_probe.claude() is None
        assert worker_probe.codex() is None

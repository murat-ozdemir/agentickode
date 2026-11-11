# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: Codex --json usage, ChatGPT credits and the codex seed upgrade."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select

from backend.models import AgentSettings
from backend.seed import seed_all
from backend.services.adapters._bimetri_codex import (
    DEFAULT_CREDIT_RATES,
    RATES_ENV,
    add_credits,
    parse_jsonl,
    parse_rates,
)
from backend.services.adapters.cli_adapter import CLIAdapter
from backend.worker.flow.executor import _bimetri_cagri_kaydi


def _jsonl(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


USAGE = {"input_tokens": 120_000, "cached_input_tokens": 100_000, "output_tokens": 4_000}
STDOUT = _jsonl(
    {"type": "thread.started", "thread_id": "t1"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "i0", "type": "agent_message", "text": "first"}},
    {"type": "item.completed", "item": {"id": "i1", "type": "command_execution"}},
    {"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "final"}},
    {"type": "turn.completed", "usage": USAGE},
)


class TestParseJsonl:
    def test_returns_last_agent_message_and_usage(self):
        message, usage = parse_jsonl(STDOUT)
        assert message == "final"
        assert usage["input_tokens"] == 120_000
        assert usage["cached_input_tokens"] == 100_000
        assert usage["output_tokens"] == 4_000
        assert usage["cost_usd"] is None
        assert usage["billing"] == "chatgpt"

    def test_plain_text_is_not_codex_jsonl(self):
        assert parse_jsonl("just the final message\n") is None

    def test_failed_turn_has_no_message_or_tokens(self):
        message, usage = parse_jsonl(
            _jsonl({"type": "turn.started"}, {"type": "turn.failed", "error": {"message": "x"}})
        )
        assert message is None
        assert "input_tokens" not in usage


class TestCredits:
    def test_parse_rates_skips_malformed_entries(self):
        rates = parse_rates("a=1/2/3, bad, b=1/2,c=x/1/1")
        assert rates == {"a": (1.0, 2.0, 3.0)}

    def test_cached_input_is_priced_separately(self):
        usage = {**USAGE, "billing": "chatgpt"}
        add_credits(usage, "gpt-6.1-terra", {})
        # 20k uncached * 25 + 100k cached * 1.25 + 4k out * 125, per 1M tokens
        assert usage["codex_credits"] == 1.125

    def test_rates_come_from_the_agent_env_var(self):
        usage = {**USAGE, "billing": "chatgpt"}
        add_credits(usage, "m", {RATES_ENV: "m=10/1/100"})
        assert usage["codex_credits"] == 0.7

    def test_unknown_model_or_non_codex_usage_gets_no_credits(self):
        usage = {**USAGE, "billing": "chatgpt"}
        add_credits(usage, "other-model", {})
        add_credits(usage, None, {})
        claude = {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.1}
        add_credits(claude, "gpt-6.1-terra", {})
        assert "codex_credits" not in usage
        assert "codex_credits" not in claude


class TestCodexAdapter:
    def test_codex_output_is_parsed(self):
        adapter = CLIAdapter(AsyncMock(), "codex")
        assert adapter._parse_json_output(STDOUT) == "final"
        assert adapter._bimetri_usage["output_tokens"] == 4_000

    def test_codex_without_json_flag_keeps_raw_output(self):
        adapter = CLIAdapter(AsyncMock(), "codex")
        assert adapter._parse_json_output("plain answer") == "plain answer"


class TestInvocationRecord:
    def test_codex_breakdown_goes_to_metadata(self):
        session = MagicMock()
        usage = {**USAGE, "billing": "chatgpt", "cost_usd": None, "codex_credits": 1.125}
        result = {"response": {"output": "final", "exit_code": 0}, "usage": usage, "model": "m"}
        _bimetri_cagri_kaydi(
            MagicMock(id=1), session, "codex", "implement", datetime.now(UTC), result, None
        )
        inv = session.add.call_args.args[0]
        assert inv.estimated_cost_usd is None
        assert inv.estimated_tokens_in == 120_000
        assert inv.metadata_ == {
            "model": "m",
            "bimetri": True,
            "cached_input_tokens": 100_000,
            "codex_credits": 1.125,
            "billing": "chatgpt",
        }


class TestSeedUpgrade:
    async def test_adds_json_flag_and_rates_keeping_custom_settings(self, db_session):
        task = "cd {workspace} && cat {instruction_file} | codex exec --skip-git-repo-check -"
        db_session.add(
            AgentSettings(
                agent_name="codex",
                display_name="Codex",
                description="test",
                command_templates={"task": task, "check": "command -v codex"},
                environment_vars={"MODEL_FOR_DIFFICULTY_EASY": "gpt-6.1-terra"},
            )
        )
        await db_session.commit()

        await seed_all(db_session)
        await seed_all(db_session)

        row = (
            await db_session.execute(
                select(AgentSettings).where(AgentSettings.agent_name == "codex")
            )
        ).scalar_one()
        assert row.command_templates["task"] == task.replace("codex exec", "codex exec --json")
        assert row.command_templates["check"] == "command -v codex"
        assert row.environment_vars == {
            "MODEL_FOR_DIFFICULTY_EASY": "gpt-6.1-terra",
            RATES_ENV: DEFAULT_CREDIT_RATES,
        }

    async def test_existing_rates_are_not_overwritten(self, db_session):
        db_session.add(
            AgentSettings(
                agent_name="codex",
                display_name="Codex",
                description="test",
                command_templates={"task": "codex exec --json -"},
                environment_vars={RATES_ENV: "m=1/1/1"},
            )
        )
        await db_session.commit()

        await seed_all(db_session)

        row = (
            await db_session.execute(
                select(AgentSettings).where(AgentSettings.agent_name == "codex")
            )
        ).scalar_one()
        assert row.environment_vars[RATES_ENV] == "m=1/1/1"
        assert row.command_templates["task"] == "codex exec --json -"

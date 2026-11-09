# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: memory proposals generated from a merged PR's discussion."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api import _pr_webhook_helpers as helpers
from backend.models import MemoryProposal
from backend.repositories.memory_proposal_repo import MemoryProposalRepository
from backend.worker.flow import _bimetri_pr_chain as chain_mod
from backend.worker.flow import _bimetri_proposals as proposals
from tests.unit.bimetri_sahte import SahteGitea

PROJECT = "Org/repo"
PR = {"number": 7, "title": "Modem parser", "body": "Closes #3\n\nAdds the parser."}


@pytest.fixture
def enabled():
    with (
        patch.object(proposals.settings, "mem0_url", "http://mem0:8000"),
        patch.object(proposals.settings, "mem0_api_key", "key"),
        patch.object(proposals.settings, "mem0_openai_api_key", "sk-test"),
    ):
        yield


@pytest.fixture
def session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


def _comment(when, who, body):
    return {"created_at": when, "user": {"login": who}, "body": body}


def _gitea(comments=None, reviews=None):
    gp = SahteGitea()
    gp.yanitlar["/repos/org/repo/issues/7/comments"] = (200, comments or [])
    gp.yanitlar["/repos/org/repo/pulls/7/reviews"] = (200, reviews or [])
    gp.yanitlar["/repos/org/repo/issues/3"] = (200, {"title": "Parser", "body": "Need it"})
    return gp


def _discussed():
    return _gitea(
        [
            _comment("2026-11-09T10:05:00Z", "agentickode", "CI red: ruff F401"),
            _comment("2026-11-09T10:01:00Z", "mozdemir", "@agentickode fix the import"),
        ],
        [{"submitted_at": "2026-11-09T10:03:00Z", "user": {"login": "rev"}, "body": "LGTM"}],
    )


def _openai(content):
    resp = httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
        request=httpx.Request("POST", proposals.OPENAI_URL),
    )
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    return client


class TestParseProposals:
    def test_keeps_valid_items_capped_and_truncated(self):
        items = [{"kind": "lesson", "text": "x" * 900}, {"kind": "bogus", "text": "a"}]
        items += [{"kind": "pitfall", "text": " p "}, {"kind": "decision", "text": ""}]
        items += [{"kind": "decision", "text": "d"}, {"kind": "lesson", "text": "4th"}]
        result = proposals.parse_proposals(json.dumps({"proposals": items}))
        assert [p["kind"] for p in result] == ["lesson", "pitfall", "decision"]
        assert len(result[0]["text"]) == proposals.MAX_TEXT_CHARS
        assert result[1]["text"] == "p"

    def test_malformed_answer_yields_nothing(self):
        assert proposals.parse_proposals("not json") == []
        assert proposals.parse_proposals('{"proposals": "x"}') == []
        assert proposals.parse_proposals("[]") == []


class TestCollectPrChain:
    async def test_empty_without_discussion(self):
        gp = _gitea([_comment("t", "a", "  ")])
        assert await chain_mod.collect_pr_chain(gp, "org/repo", PR) == ""

    async def test_includes_issue_and_orders_discussion(self):
        text = await chain_mod.collect_pr_chain(_discussed(), "org/repo", PR)
        assert text.startswith("# PR #7: Modem parser")
        assert "## Linked issue #3: Parser" in text
        order = [text.index(s) for s in ("fix the import", "LGTM", "ruff F401")]
        assert order == sorted(order)


class TestProposeForMerge:
    async def test_disabled_without_openai_key(self, enabled):
        with patch.object(proposals.settings, "mem0_openai_api_key", ""):
            assert await proposals.propose_for_merge(_gitea(), PROJECT, "org/repo", PR) == (
                "disabled"
            )

    async def test_no_discussion_skips_llm(self, enabled, session_factory):
        client = _openai("{}")
        with patch.object(proposals, "get_http_client", return_value=client):
            outcome = await proposals.propose_for_merge(
                _gitea(), PROJECT, "org/repo", PR, session_factory
            )
        assert outcome == "no-discussion"
        client.post.assert_not_called()

    async def test_stores_pending_rows_and_sends_known_records(self, enabled, session_factory):
        async with session_factory() as s:
            s.add(MemoryProposal(project=PROJECT, pr_number=1, kind="pitfall", text="Old idea"))
            s.add(
                MemoryProposal(
                    project=PROJECT,
                    pr_number=2,
                    kind="decision",
                    text="PR summary",
                    status="rejected",
                )
            )
            # An agent's proposal on the same PR must not count as "already proposed".
            s.add(
                MemoryProposal(
                    project=PROJECT, pr_number=7, kind="lesson", text="Agent", source="agent"
                )
            )
            await s.commit()
        known = [
            {"memory": "Use uv", "metadata": {"tur": "ders"}},
            {"memory": "PR #6 ...", "metadata": {"tur": "ozellik_gecmisi"}},
        ]
        answer = {"proposals": [{"kind": "lesson", "text": "Run ruff before push"}]}
        client = _openai(json.dumps(answer))
        with (
            patch.object(proposals, "get_http_client", return_value=client),
            patch.object(proposals, "list_memories", AsyncMock(return_value=known)),
        ):
            outcome = await proposals.propose_for_merge(
                _discussed(), PROJECT, "org/repo", PR, session_factory
            )
        assert outcome == "1 proposals"
        body = client.post.call_args.kwargs["json"]
        assert body["model"] == "gpt-5-mini"
        assert client.post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-test"
        user_msg = body["messages"][1]["content"]
        known_part, rejected_part = user_msg.split("Rejected by a human earlier:")
        assert "- Use uv" in known_part and "- Old idea" in known_part
        assert "PR summary" not in known_part and "- PR summary" in rejected_part
        assert "summary of what this PR changed" in body["messages"][0]["content"]
        assert "PR #6" not in user_msg
        async with session_factory() as s:
            rows = await MemoryProposalRepository(s).list_proposals(
                status="pending", project=PROJECT
            )
        assert [(r.pr_number, r.kind, r.text) for r in rows if r.source == "merge"] == [
            (7, "lesson", "Run ruff before push"),
            (1, "pitfall", "Old idea"),
        ]

    async def test_skips_pr_that_already_has_proposals(self, enabled, session_factory):
        async with session_factory() as s:
            s.add(MemoryProposal(project=PROJECT, pr_number=7, kind="lesson", text="x"))
            await s.commit()
        outcome = await proposals.propose_for_merge(
            _discussed(), PROJECT, "org/repo", PR, session_factory
        )
        assert outcome == "exists"

    async def test_background_error_is_only_logged(self, enabled, caplog):
        with patch.object(proposals, "propose_for_merge", AsyncMock(side_effect=RuntimeError)):
            proposals.schedule_proposals(_gitea(), PROJECT, "org/repo", PR)
            await asyncio.gather(*proposals._tasks)
        assert "PR #7 memory proposals failed" in caplog.text
        assert not proposals._tasks


class TestMergeWebhook:
    async def test_merge_schedules_proposals(self):
        project = SimpleNamespace(
            project_id="p", repo_owner="Org", repo_name="repo", workspace_server_id=None
        )
        repo = MagicMock(get_by_git_repo=AsyncMock(return_value=project))
        gp = MagicMock(set_status_label=AsyncMock())
        body = {"pull_request": dict(PR), "repository": {"full_name": "org/repo"}}
        with (
            patch("backend.worker.phases._helpers.get_project_token", AsyncMock(return_value="t")),
            patch("backend.services.git.get_git_provider", return_value=gp),
            patch("backend.worker.flow._bimetri_ozellik.arka_planda_yaz"),
            patch.object(proposals, "schedule_proposals") as schedule,
        ):
            await helpers._bimetri_pr_merged(body, MagicMock(), repo)
        schedule.assert_called_once_with(gp, PROJECT, "org/repo", body["pull_request"])

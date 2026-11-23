# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: agent file links in PR bodies/comments point at the branch on Gitea."""

from unittest.mock import AsyncMock, MagicMock

import httpx

from backend.services.git import GiteaProvider
from backend.services.git._bimetri_links import fix_file_links, has_file_links

WEB = "https://git.test/Org/repo"
BR = "feature/99-alarm"
SRC = f"{WEB}/src/branch/{BR}"


def _fix(body: str) -> str:
    return fix_file_links(body, WEB, "Org", "repo", BR)


class TestFixFileLinks:
    def test_workspace_path_link_points_at_branch(self):
        # PR #121: Codex wrote the absolute workspace path, Gitea gave a 404
        body = "[A.java](/workspaces/Org/repo/Mod/src/A.java)"
        assert _fix(body) == f"[A.java]({SRC}/Mod/src/A.java)"

    def test_line_suffix_becomes_gitea_anchor(self):
        assert _fix("[a](/workspaces/Org/repo/a.py:42)") == f"[a]({SRC}/a.py#L42)"
        assert _fix("[a](/workspaces/Org/repo/a.py:4-9)") == f"[a]({SRC}/a.py#L4-L9)"
        assert _fix("[a](/workspaces/Org/repo/a.py:4:7)") == f"[a]({SRC}/a.py#L4)"

    def test_repo_relative_and_cluster_paths(self):
        assert _fix("[a](Mod/a.java)") == f"[a]({SRC}/Mod/a.java)"
        assert _fix("[a](./a.md)") == f"[a]({SRC}/a.md)"
        assert _fix("[a](/workspaces/task-7/a.md)") == f"[a]({SRC}/a.md)"
        assert _fix("[a](file:///workspaces/Org/repo/a.md)") == f"[a]({SRC}/a.md)"

    def test_reference_definition_is_rewritten(self):
        assert _fix("see [a]\n\n[a]: /workspaces/Org/repo/a.md\n") == (
            f"see [a]\n\n[a]: {SRC}/a.md\n"
        )

    def test_other_links_are_kept(self):
        for body in (
            "[#307](https://crew.test/runs/307)",
            "[x](#anchor)",
            "[x](issues/3)",
            "[x](../other)",
            "[x](/Org/repo/issues/3)",
            "[x](mailto:a@b.c)",
            "plain text without links",
        ):
            assert _fix(body) == body
            assert not has_file_links(body, "Org", "repo")

    def test_plain_workspace_mention_loses_prefix(self):
        assert _fix("edited /workspaces/Org/repo/a.md") == "edited a.md"


def _resp(status: int, data: dict) -> MagicMock:
    r = MagicMock(status_code=status)
    r.json.return_value = data
    r.raise_for_status = MagicMock()
    return r


class TestGiteaProviderLinks:
    def _provider(self, gets: list[MagicMock]) -> tuple[GiteaProvider, MagicMock]:
        client = MagicMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(side_effect=gets)
        client.post = AsyncMock(return_value=_resp(201, {"html_url": f"{WEB}/pulls/5"}))
        return GiteaProvider(client, base_url="https://git.test", token="t"), client

    async def test_comment_links_use_pr_head_branch(self):
        repo = _resp(200, {"html_url": WEB, "default_branch": "master"})
        pr = _resp(200, {"head": {"ref": BR}})
        gp, client = self._provider([repo, pr])
        await gp.post_pr_comment("Org/repo", 5, "[a](/workspaces/Org/repo/a.md)")
        assert client.post.call_args.kwargs["json"]["body"] == f"[a]({SRC}/a.md)"

    async def test_issue_comment_falls_back_to_issue_ref(self):
        repo = _resp(200, {"html_url": WEB, "default_branch": "master"})
        gp, client = self._provider([repo, _resp(404, {}), _resp(200, {"ref": f"refs/heads/{BR}"})])
        await gp.post_pr_comment("Org/repo", 99, "[a](a.md)")
        assert client.post.call_args.kwargs["json"]["body"] == f"[a]({SRC}/a.md)"

    async def test_create_pr_uses_head_branch(self):
        gp, client = self._provider([_resp(200, {"html_url": WEB})])
        await gp.create_pr("Org/repo", "t", "[a](/workspaces/Org/repo/a.md)", BR, "master")
        assert client.post.call_args.kwargs["json"]["body"] == f"[a]({SRC}/a.md)"

    async def test_body_without_links_makes_no_extra_call(self):
        gp, client = self._provider([])
        await gp.post_pr_comment("Org/repo", 5, "LGTM")
        client.get.assert_not_called()

    async def test_lookup_failure_posts_original_body(self):
        gp, client = self._provider([httpx.ConnectError("down")])
        await gp.post_pr_comment("Org/repo", 5, "[a](a.md)")
        assert client.post.call_args.kwargs["json"]["body"] == "[a](a.md)"

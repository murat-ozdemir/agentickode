# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: status/* label changes move the issue's project board card."""

import httpx

from backend.services.git._bimetri_board import column_for, move_issue_card, project_api_base
from backend.services.git.gitea import GiteaProvider

API = "https://gitea.test/api/v1"
COLUMNS = [
    {"id": 1, "title": "Backlog"},
    {"id": 2, "title": "To Do"},
    {"id": 3, "title": "In Progress"},
    {"id": 4, "title": "Review"},
    {"id": 5, "title": "Done"},
]


def test_project_api_base_by_project_type():
    org = {"id": 9, "type": "organization"}
    repo = {"id": 9, "type": "repository"}
    assert project_api_base(API, "myorg/r", org) == f"{API}/orgs/myorg/projects/9"
    assert project_api_base(API, "myorg/r", repo) == f"{API}/repos/myorg/r/projects/9"
    assert project_api_base(API, "myorg/r", {"id": 9, "type": "individual"}) is None


def test_column_for_matches_title_case_insensitively():
    assert column_for(COLUMNS, "status/in-progress")["id"] == 3
    assert column_for([{"id": 7, "title": "todo"}], "status/open")["id"] == 7
    assert column_for(COLUMNS, "status/on-hold") is None
    assert column_for(COLUMNS, "ai-task") is None


def _gitea(moves: list, projects: list, move_status: int = 200):
    """Fake Gitea: issue #5 (global id 500) in the given projects."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/issues/5"):
            return httpx.Response(200, json={"id": 500, "number": 5, "projects": projects})
        if request.method == "GET" and path.endswith("/columns"):
            return httpx.Response(200, json=COLUMNS)
        if request.method == "POST" and path.endswith("/move"):
            moves.append((path, request.read()))
            return httpx.Response(move_status)
        if path.endswith("/issues/5/labels") and request.method == "GET":
            return httpx.Response(200, json=[{"id": 11, "name": "status/open"}])
        if path.endswith("/labels") and request.method == "GET":
            return httpx.Response(200, json=[{"id": 12, "name": "status/in-progress"}])
        return httpx.Response(200, json=[])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_move_issue_card_moves_on_each_project():
    moves: list = []
    projects = [
        {"id": 3, "type": "organization", "title": "Org board"},
        {"id": 4, "type": "repository", "title": "Repo board"},
    ]
    async with _gitea(moves, projects) as client:
        moved = await move_issue_card(client, API, {}, "myorg/r", 5, "status/in-progress")
    assert moved == ["Org board", "Repo board"]
    assert moves[0][0] == "/api/v1/orgs/myorg/projects/3/issues/500/move"
    assert moves[1][0] == "/api/v1/repos/myorg/r/projects/4/issues/500/move"
    assert b'"column_id":3' in moves[0][1].replace(b" ", b"")


async def test_move_issue_card_skips_issue_without_project():
    moves: list = []
    async with _gitea(moves, []) as client:
        assert await move_issue_card(client, API, {}, "myorg/r", 5, "status/review") == []
    assert moves == []


async def test_set_status_label_survives_failed_card_move():
    moves: list = []
    projects = [{"id": 3, "type": "organization", "title": "Org board"}]
    async with _gitea(moves, projects, move_status=500) as client:
        provider = GiteaProvider(client, base_url="https://gitea.test", token="tok")
        await provider.set_status_label("myorg/r", 5, "status/in-progress")
    assert len(moves) == 1

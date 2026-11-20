# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: existing clones get the current token; status label swaps add before delete."""

from unittest.mock import AsyncMock

import httpx
import pytest

from backend.services.git import RemoteGitError, RemoteGitOps
from backend.services.git.gitea import GiteaProvider
from backend.services.git.remote_ops import _has_credentials
from backend.services.workspace.ssh_service import SSHCommandError
from backend.worker.phases import workspace_setup

SECRET = "s3cr3t-token"
AUTH_URL = f"https://agentickode:{SECRET}@gitea.test/org/repo.git"


@pytest.fixture()
def mock_ssh():
    ssh = AsyncMock()
    ssh.hostname = "10.0.0.1"
    ssh.port = 22
    return ssh


def test_has_credentials():
    assert _has_credentials(AUTH_URL)
    assert not _has_credentials("https://gitea.test/org/repo.git")
    assert not _has_credentials("git@gitea.test:org/repo.git")
    assert not _has_credentials("https://gitea.test/org/a@b.git")


async def test_set_origin_url_error_hides_token(mock_ssh):
    mock_ssh.run_command.return_value = ("", f"fatal: bad {AUTH_URL}", 2)
    with pytest.raises(RemoteGitError) as exc:
        await RemoteGitOps(mock_ssh).set_origin_url("/ws", AUTH_URL)
    assert SECRET not in str(exc.value)
    assert "git remote set-url origin" in mock_ssh.run_command.call_args[0][0]


async def test_set_origin_url_exception_hides_token(mock_ssh):
    mock_ssh.run_command.side_effect = OSError(f"boom {AUTH_URL}")
    with pytest.raises(RemoteGitError) as exc:
        await RemoteGitOps(mock_ssh).set_origin_url("/ws", AUTH_URL)
    assert SECRET not in str(exc.value)
    assert exc.value.__cause__ is None


async def test_set_origin_url_ssh_error_hides_token(mock_ssh):
    mock_ssh.run_command.side_effect = SSHCommandError(
        f"SSH command timed out: {AUTH_URL}", hostname="h", command=AUTH_URL
    )
    with pytest.raises(RemoteGitError) as exc:
        await RemoteGitOps(mock_ssh).set_origin_url("/ws", AUTH_URL)
    assert SECRET not in str(exc.value)
    assert exc.value.__cause__ is None


async def test_clone_or_pull_refreshes_origin_before_fetch(mock_ssh):
    mock_ssh.run_command.return_value = ("", "", 0)
    await RemoteGitOps(mock_ssh).clone_or_pull(AUTH_URL, "/ws/repo")
    cmds = [c[0][0] for c in mock_ssh.run_command.call_args_list]
    set_url = next(i for i, c in enumerate(cmds) if "remote set-url origin" in c)
    fetch = next(i for i, c in enumerate(cmds) if "git fetch origin" in c)
    assert set_url < fetch


async def test_clone_or_pull_leaves_plain_remote_alone(mock_ssh):
    mock_ssh.run_command.return_value = ("", "", 0)
    await RemoteGitOps(mock_ssh).clone_or_pull("git@gitea.test:org/repo.git", "/ws/repo")
    cmds = [c[0][0] for c in mock_ssh.run_command.call_args_list]
    assert not any("set-url" in c for c in cmds)


class _Run:
    repo_owner = "org"
    repo_name = "repo"
    git_provider = "gitea"
    default_branch = "main"


async def test_refresh_origin_sets_https_auth_url(monkeypatch):
    monkeypatch.setattr(
        workspace_setup, "get_auth_url", AsyncMock(return_value=(AUTH_URL, "https"))
    )
    git = AsyncMock()
    log = AsyncMock()
    await workspace_setup._refresh_origin(_Run(), {}, AsyncMock(), git, "/ws", "tok", log)
    git.set_origin_url.assert_awaited_once_with("/ws", AUTH_URL)
    assert all(SECRET not in str(c) for c in log.call_args_list)


async def test_refresh_origin_skips_ssh(monkeypatch):
    monkeypatch.setattr(
        workspace_setup,
        "get_auth_url",
        AsyncMock(return_value=("git@gitea.test:org/repo.git", "ssh")),
    )
    git = AsyncMock()
    await workspace_setup._refresh_origin(_Run(), {}, AsyncMock(), git, "/ws", None, AsyncMock())
    git.set_origin_url.assert_not_awaited()


async def test_refresh_origin_skips_when_repo_unknown():
    run = _Run()
    run.repo_owner = None
    git = AsyncMock()
    log = AsyncMock()
    await workspace_setup._refresh_origin(run, {}, AsyncMock(), git, "/ws", None, log)
    git.set_origin_url.assert_not_awaited()
    log.assert_awaited_once()


async def test_status_label_added_before_old_removed():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((request.method, path))
        if request.method == "GET" and path.endswith("/issues/10/labels"):
            return httpx.Response(
                200, json=[{"id": 1, "name": "ai-test"}, {"id": 2, "name": "status/review"}]
            )
        if request.method == "GET" and path.endswith("/repos/org/r/labels"):
            return httpx.Response(200, json=[{"id": 3, "name": "status/on-hold"}])
        if request.method == "GET" and path.endswith("/issues/10"):
            return httpx.Response(200, json={"id": 1000, "projects": []})
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GiteaProvider(client, base_url="https://gitea.test", token="tok")
        await provider.set_status_label("org/r", 10, "status/on-hold")

    post = calls.index(("POST", "/api/v1/repos/org/r/issues/10/labels"))
    delete = calls.index(("DELETE", "/api/v1/repos/org/r/issues/10/labels/2"))
    assert post < delete
    assert ("DELETE", "/api/v1/repos/org/r/issues/10/labels/1") not in calls

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: runs ON the worker (``python3 -``) as the user that runs the agents.

Standard library only. Reads which subscription account each agent CLI is logged in to and
that account's 5-hour / weekly usage, and prints one JSON object keyed by provider. Tokens
stay on the worker: only account ids, e-mail, plan and the usage numbers are printed.
"""

import contextlib
import json
import os
import select
import shutil
import subprocess
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
MODEL_SLOTS = ("seven_day_opus", "seven_day_sonnet")
ACCOUNT_KEYS = ("accountUuid", "emailAddress", "organizationUuid", "organizationName")
# The CLI refreshes its own login before a request; no command refreshes it without one, and the
# token endpoint is not public. So an idle worker with an expired token gets the smallest call.
REFRESH_CMD = [
    "claude", "-p", "Reply with: ok", "--model", "haiku", "--max-turns", "1",
    "--strict-mcp-config", "--no-session-persistence",
]
REFRESH_TIMEOUT = 60


def _load(path):
    with open(path) as f:
        return json.load(f)


def _expired(creds):
    expires = creds.get("expiresAt") or 0
    return bool(expires) and expires / 1000 < time.time()


def _claude_running():
    """True when this user runs a claude CLI process (an agent call is on)."""
    uid = os.getuid()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid or int(pid) == os.getpid():
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        if any(os.path.basename(a) == b"claude" for a in argv[:2]):
            return True
    return False


def _refresh(path):
    """Let the CLI refresh its expired login; the new credentials, or an error text."""
    if _claude_running():
        return None, "token expired; an agent call is running and refreshes it"
    if not shutil.which("claude"):
        return None, "token expired; claude CLI not on PATH"
    try:
        subprocess.run(
            REFRESH_CMD, cwd="/tmp", stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=REFRESH_TIMEOUT, check=False,
        )
        creds = _load(path)["claudeAiOauth"]
    except Exception as e:
        return None, f"token expired; refresh failed: {type(e).__name__}"
    if _expired(creds):
        return None, "token expired; refresh call did not renew it"
    return creds, None


def claude():
    path = os.path.join(HOME, ".claude", ".credentials.json")
    try:
        creds = _load(path)["claudeAiOauth"]
    except FileNotFoundError:
        return None
    except Exception as e:
        return {"error": f"credentials unreadable: {type(e).__name__}"}
    try:
        acct = _load(os.path.join(HOME, ".claude.json")).get("oauthAccount") or {}
    except Exception:
        acct = {}
    out = {
        "account": {k: acct.get(k) for k in ACCOUNT_KEYS},
        "plan": creds.get("subscriptionType"),
        "tier": creds.get("rateLimitTier"),
    }
    if _expired(creds):
        creds, error = _refresh(path)
        if error:
            out["error"] = error
            return out
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": "Bearer " + creds.get("accessToken", ""),
            "anthropic-beta": "oauth-2025-04-20",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            usage = json.load(resp)
        # windows, per-model weekly slots, scoped limits and usage-credit spend; no ids/tokens
        keep = ("five_hour", "seven_day", "limits", "spend", "extra_usage")
        out["usage"] = {k: v for k, v in usage.items() if k in keep or k in MODEL_SLOTS}
    except urllib.error.HTTPError as e:
        out["error"] = f"usage request failed: HTTP {e.code}"
    except Exception as e:
        out["error"] = f"usage request failed: {type(e).__name__}"
    return out


def _app_server(requests, deadline_s=20):
    proc = subprocess.Popen(
        ["codex", "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    stdin, stdout = proc.stdin, proc.stdout
    assert stdin is not None and stdout is not None
    try:
        for msg in requests:
            stdin.write(json.dumps(msg) + "\n")
        stdin.flush()
        wanted = {m["id"] for m in requests if "id" in m}
        replies, end = {}, time.time() + deadline_s
        while wanted - replies.keys() and time.time() < end:
            ready, _, _ = select.select([stdout], [], [], 1)
            if not ready:
                continue
            line = stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") in wanted:
                replies[msg["id"]] = msg
        return replies
    finally:
        proc.kill()


def codex():
    auth = os.path.join(HOME, ".codex", "auth.json")
    if not os.path.exists(auth) or not shutil.which("codex"):
        return None
    info = {"name": "agentickode", "title": "AgenticKode", "version": "1.0"}
    replies = _app_server(
        [
            {"method": "initialize", "id": 0, "params": {"clientInfo": info}},
            {"method": "initialized"},
            {"method": "account/read", "id": 1, "params": {}},
            {"method": "account/rateLimits/read", "id": 2},
        ]
    )
    read = (replies.get(1) or {}).get("result") or {}
    account = read.get("account") or {}
    out = {
        "account": {k: account.get(k) for k in ("type", "email", "planType")},
        "account_id": (read.get("workspaceRouting") or {}).get("chatgptAccountId"),
    }
    if not out["account_id"]:  # account/read now and then has no result; the login names it
        with contextlib.suppress(Exception):
            out["account_id"] = _load(auth)["tokens"]["account_id"]
    limits = replies.get(2) or {}
    if "result" in limits:
        res = limits["result"]
        out["limits"] = (res.get("rateLimitsByLimitId") or {}).get("codex") or res.get("rateLimits")
    else:
        err = (limits.get("error") or {}).get("message") or "no reply from codex app-server"
        out["error"] = f"rate limits unavailable: {err}"
    return out


def main():
    result = {}
    for name, probe in (("claude", claude), ("codex", codex)):
        try:
            section = probe()
        except Exception as e:
            section = {"error": f"probe crashed: {type(e).__name__}"}
        if section is not None:
            result[name] = section
    print(json.dumps(result))


if __name__ == "__main__":
    main()

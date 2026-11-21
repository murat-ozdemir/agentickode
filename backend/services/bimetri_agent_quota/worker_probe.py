# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: runs ON the worker (``python3 -``) as the user that runs the agents.

Standard library only. Reads which subscription account each agent CLI is logged in to and
that account's 5-hour / weekly usage, and prints one JSON object keyed by provider. Tokens
stay on the worker: only account ids, e-mail, plan and the usage numbers are printed.
"""

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


def _load(path):
    with open(path) as f:
        return json.load(f)


def claude():
    try:
        creds = _load(os.path.join(HOME, ".claude", ".credentials.json"))["claudeAiOauth"]
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
    expires = creds.get("expiresAt") or 0
    if expires and expires / 1000 < time.time():
        out["error"] = "token expired; the CLI refreshes it on its next run"
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
    if not os.path.exists(os.path.join(HOME, ".codex", "auth.json")) or not shutil.which("codex"):
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

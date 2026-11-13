# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: deleting a chat session removes the agent's own session files too.

The chat agent runs ``claude -p --session-id <id>`` in the backend container, so Claude keeps
the conversation under the run-as user's ``~/.claude``. Deleting only the database row would
leave the full transcript there.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import uuid
from pathlib import Path


def agent_home(run_as_user: str | None) -> Path:
    """Home of the user the chat agent runs as (the backend process user when None)."""
    if run_as_user:
        import pwd

        with contextlib.suppress(KeyError):
            return Path(pwd.getpwnam(run_as_user).pw_dir)
    return Path(os.path.expanduser("~"))


def remove_claude_session_files(session_id: str, home: Path) -> list[Path]:
    """Remove Claude's files for one session under ``home/.claude``; the removed paths.

    Only a UUID is accepted, so the id can never point outside the session's own files.
    """
    try:
        sid = str(uuid.UUID(session_id))
    except ValueError:
        return []
    root = home / ".claude"
    candidates = [
        *root.glob(f"projects/*/{sid}.jsonl"),
        *root.glob(f"projects/*/{sid}"),
        root / "file-history" / sid,
        root / "session-env" / sid,
        *root.glob(f"todos/{sid}-*.json"),
    ]
    removed = []
    for path in candidates:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists() or path.is_symlink():
            with contextlib.suppress(OSError):
                path.unlink()
        else:
            continue
        removed.append(path)
    return removed

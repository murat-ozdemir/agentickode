# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (D2 measurement): what one agent call with the code graph costs.

The Code graph card's read savings only cover file reads; the quota goes on turns times context.
This gives the plain per-call figures of the graph calls (``metadata_.graph`` set) in range:
average tokens (in + out) and average turns. ``shell_reads`` sums the source files Codex
printed in the shell (cat, sed -n, ...) over the ``shell_read_calls`` that report it.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class TokenRow:
    tokens: int
    turns: int | None = None
    shell_reads: int | None = None  # Codex: commands that printed a source file


def _avg(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def build(rows: list[TokenRow]) -> dict[str, Any]:
    tokens = _avg([r.tokens for r in rows])
    turns = [r.turns for r in rows if r.turns is not None]
    reads = [r.shell_reads for r in rows if r.shell_reads is not None]
    avg_turns = _avg(turns)
    return {
        "calls": len(rows),
        "tokens_per_call": round(tokens) if tokens is not None else None,
        "turns_per_call": round(avg_turns, 1) if avg_turns is not None else None,
        "turn_calls": len(turns),
        "shell_reads": sum(reads),
        "shell_read_calls": len(reads),
    }

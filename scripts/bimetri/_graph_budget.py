"""bimetri patch (graf tasarruf planı, Faz 1): one agent call's graph reading budget and dedupe.

agent-graph-mcp.sh puts this file after _graph_reply.py in graph_flow.py. The MCP server lives as
long as one agent call, so its Ledger is that call's:

- budget: graph_read and graph_callers send at most RUN_CHARS in all. Past it only answers up to
  SMALL_CHARS go through (a use site, a short range, a small method); larger ones get
  `budget_exhausted`. Every answer ends with what is left.
- dedupe: code already sent (same file, unchanged on disk) is not sent again; a short note names
  the call that sent it. The same request right after that note is served (the agent's context
  may have been compacted), as the search gate does after its first refusal.
"""

RUN_CHARS = 60_000
SMALL_CHARS = 1_500
BUDGET_EXHAUSTED = (
    "budget_exhausted: graph_read and graph_callers sent {used:,} of {limit:,} characters in "
    "this agent call. Answers up to {small:,} characters still come through: path:LINE, a short "
    "path:START-END (about 30 lines) or a small path::Symbol. Write the change with what you have."
)
ALREADY_SENT = (
    "{target}: already sent by graph call #{call} and unchanged since; use that text. If it is "
    "no longer in your context, call again with the same argument."
)


def _sent_by(ranges: list, sent: list) -> "int | None":
    """The latest call among those that sent every line of ranges; None if a line is new."""
    calls = []
    for start, end in ranges:
        found = [call for s, e, call in sent if s <= start and end <= e]
        if not found:
            return None
        calls.append(min(found))
    return max(calls) if calls else None


class Ledger:
    def __init__(self, limit: int = RUN_CHARS) -> None:
        self.limit, self.used, self.calls = limit, 0, 0
        self.lines: dict = {}  # (rel, stamp) -> [(start, end, graph call)] sent
        self.first: dict = {}  # request key (outline, callers) -> graph call that sent it
        self.noted: set = set()  # requests answered with ALREADY_SENT

    def repeat(self, target: str, key, ranges: "list | None" = None) -> "str | None":
        """ALREADY_SENT if key's answer (or every line of ranges) went out before, else None."""
        self.calls += 1
        sent = self.lines.get(key, [])
        call = self.first.get(key) if ranges is None else _sent_by(ranges, sent)
        if call is None or target in self.noted:
            return None
        self.noted.add(target)
        return ALREADY_SENT.format(target=target, call=call)

    def send(self, text: str, key, ranges: "list | None" = None) -> str:
        """text with the budget line, or BUDGET_EXHAUSTED; records what went out."""
        if self.used + len(text) > self.limit and len(text) > SMALL_CHARS:
            return BUDGET_EXHAUSTED.format(used=self.used, limit=self.limit, small=SMALL_CHARS)
        self.used += len(text)
        if ranges is None:
            self.first.setdefault(key, self.calls)
        else:
            self.lines.setdefault(key, []).extend((s, e, self.calls) for s, e in ranges)
        left = max(self.limit - self.used, 0)
        return f"{text}\n[graph budget: {left:,} of {self.limit:,} characters left]"

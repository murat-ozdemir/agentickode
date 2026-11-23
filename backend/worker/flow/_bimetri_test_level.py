# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 3): the test agent's difficulty tier and effort.

The test agent checks acceptance criteria with targeted tests; it needs less than the coder.
- Tier: the issue's `difficulty/` label. The auto-fix loop (_bimetri_oto.zorluk_artir) raises
  only the PR's label for the fix agent, so the test agent's model stays the issue's.
- Effort: one level below the chosen effort (`effort/` label or EFFORT_FOR_DIFFICULTY_*),
  at most `high`, at least `low`. No effort chosen: the model's default.
"""

EFFORTS = ("low", "medium", "high", "xhigh", "max")
TEST_EFFORT_CAP = "high"


def label_value(labels: list, group: str) -> "str | None":
    """First `group/value` label's value, normalised like the executor's labels."""
    for raw in labels:
        label = str(raw).strip().lower().replace("ı", "i")
        if label.startswith(f"{group}/"):
            return label.split("/", 1)[1]
    return None


def tier_for_test(issue_labels: list, tier: str) -> str:
    """The issue's difficulty tier (upper case); `tier` when the issue has none."""
    found = label_value(issue_labels, "difficulty")
    return found.upper() if found else tier


def effort_for_test(effort: str) -> str:
    """One level below `effort`, capped at TEST_EFFORT_CAP, at least the lowest level."""
    if effort not in EFFORTS:
        return effort
    level = min(max(EFFORTS.index(effort) - 1, 0), EFFORTS.index(TEST_EFFORT_CAP))
    return EFFORTS[level]

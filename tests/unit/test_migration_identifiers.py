# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: raw SQL in migrations must quote PostgreSQL reserved words.

The tests run on SQLite, which accepts ``similar`` as a bare column name; PostgreSQL does not
(``SIMILAR TO``), so migration 051 broke the backend start on dev-1 while every test passed.
"""

import re
from pathlib import Path

from sqlalchemy.dialects.postgresql.base import RESERVED_WORDS

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
# Unquoted identifier after ADD/DROP/RENAME COLUMN (with optional IF [NOT] EXISTS)
COLUMN = re.compile(
    r"\b(?:ADD|DROP|RENAME)\s+COLUMN\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?([A-Za-z_]\w*)",
    re.IGNORECASE,
)


def unquoted_reserved(source: str) -> list[str]:
    return [m.group(1) for m in COLUMN.finditer(source) if m.group(1).lower() in RESERVED_WORDS]


class TestMigrationIdentifiers:
    def test_detects_bare_reserved_column(self):
        sql = "ALTER TABLE t ADD COLUMN IF NOT EXISTS similar JSON"
        assert unquoted_reserved(sql) == ["similar"]

    def test_accepts_quoted_reserved_column(self):
        assert unquoted_reserved('ALTER TABLE t DROP COLUMN IF EXISTS "similar"') == []

    def test_no_migration_uses_a_bare_reserved_column(self):
        found = {
            path.name: names
            for path in sorted(VERSIONS.glob("*.py"))
            if (names := unquoted_reserved(path.read_text(encoding="utf-8")))
        }
        assert found == {}

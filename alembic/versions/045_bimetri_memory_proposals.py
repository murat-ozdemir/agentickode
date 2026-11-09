# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: project-memory proposals table.

The revision id is prefixed (``b045_...``) so it cannot collide with an upstream ``045``.
If upstream adds its own revision on top of ``044``, add a merge revision
(``alembic merge heads``).
"""

from alembic import op

revision = "b045_memory_proposals"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS bimetri_memory_proposals (
            id SERIAL PRIMARY KEY,
            project TEXT NOT NULL,
            pr_number INTEGER NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            mem0_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            decided_at TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bimetri_memory_proposals_project_pr "
        "ON bimetri_memory_proposals (project, pr_number)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bimetri_memory_proposals_status "
        "ON bimetri_memory_proposals (status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bimetri_memory_proposals")

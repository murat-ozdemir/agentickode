# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: memory proposals keep the similar records found in mem0 and may replace one.

``similar`` lists the records the duplicate check found when the agent proposed;
``replaces_mem0_id`` makes approval update that record instead of adding a new one.
"""

from alembic import op

revision = "b051_memory_proposal_similar"
down_revision = "b050_chain_notebooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE bimetri_memory_proposals ADD COLUMN IF NOT EXISTS similar JSON")
    op.execute(
        "ALTER TABLE bimetri_memory_proposals ADD COLUMN IF NOT EXISTS replaces_mem0_id TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bimetri_memory_proposals DROP COLUMN IF EXISTS replaces_mem0_id")
    op.execute("ALTER TABLE bimetri_memory_proposals DROP COLUMN IF EXISTS similar")

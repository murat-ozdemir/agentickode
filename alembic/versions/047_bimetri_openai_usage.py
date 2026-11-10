# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: OpenAI API spend (daily, from the Costs API) and hand-entered credits."""

from alembic import op

revision = "b047_openai_usage"
down_revision = "b046_memory_proposal_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS bimetri_openai_credits (
            id SERIAL PRIMARY KEY,
            amount_usd NUMERIC(12, 2) NOT NULL,
            credited_on DATE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS bimetri_openai_costs (
            day DATE PRIMARY KEY,
            amount_usd NUMERIC(16, 8) NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bimetri_openai_costs")
    op.execute("DROP TABLE IF EXISTS bimetri_openai_credits")

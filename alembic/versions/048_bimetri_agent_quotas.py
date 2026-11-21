# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: 5-hour / weekly limits of the agent subscription accounts."""

from alembic import op

revision = "b048_agent_quotas"
down_revision = "b047_openai_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS bimetri_agent_quota_accounts (
            id SERIAL PRIMARY KEY,
            provider TEXT NOT NULL,
            account_key TEXT NOT NULL,
            email TEXT,
            plan TEXT,
            org_name TEXT,
            windows JSONB NOT NULL DEFAULT '[]',
            limit_reached BOOLEAN NOT NULL DEFAULT false,
            workers JSONB NOT NULL DEFAULT '[]',
            error TEXT,
            observed_at TIMESTAMPTZ,
            checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (provider, account_key)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bimetri_agent_quota_accounts")

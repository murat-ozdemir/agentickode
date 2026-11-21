# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: usage-credit spend of an agent subscription account."""

from alembic import op

revision = "b049_agent_quota_credits"
down_revision = "b048_agent_quotas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE bimetri_agent_quota_accounts ADD COLUMN IF NOT EXISTS credits JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE bimetri_agent_quota_accounts DROP COLUMN IF EXISTS credits")

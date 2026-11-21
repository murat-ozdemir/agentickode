# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: last known 5-hour / weekly limits of each agent subscription account."""

from sqlalchemy import Boolean, Column, DateTime, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB

from backend.models.base import Base


class AgentQuotaAccount(Base):
    """One subscription account (Claude, Codex, ...) and the workers that use it.

    ``windows`` holds ``{key, label, minutes, used_percent, resets_at}`` items and ``workers``
    holds ``{server_id, server_name, user}`` items. Tokens never reach this table.
    """

    __tablename__ = "bimetri_agent_quota_accounts"
    __table_args__ = (UniqueConstraint("provider", "account_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(Text, nullable=False)
    account_key = Column(Text, nullable=False)
    email = Column(Text, nullable=True)
    plan = Column(Text, nullable=True)
    org_name = Column(Text, nullable=True)
    windows = Column(JSONB, nullable=False, default=list)
    limit_reached = Column(Boolean, nullable=False, default=False)
    workers = Column(JSONB, nullable=False, default=list)
    error = Column(Text, nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=True)  # last successful read
    checked_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: project-memory proposals awaiting human review.

On a PR merge an LLM reads the PR's discussion and proposes up to 3 lessons, pitfalls or
decisions. They wait here until someone approves (written to mem0) or rejects them.
"""

from sqlalchemy import Column, DateTime, Index, Integer, Text, func

from backend.models.base import Base

PROPOSAL_KINDS = ("lesson", "pitfall", "decision")
PROPOSAL_STATUSES = ("pending", "approved", "rejected")


class MemoryProposal(Base):
    __tablename__ = "bimetri_memory_proposals"
    __table_args__ = (
        Index("ix_bimetri_memory_proposals_project_pr", "project", "pr_number"),
        Index("ix_bimetri_memory_proposals_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project = Column(Text, nullable=False)  # "<owner>/<repo>", the mem0 user_id
    pr_number = Column(Integer, nullable=False)
    kind = Column(Text, nullable=False)  # one of PROPOSAL_KINDS
    text = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")  # one of PROPOSAL_STATUSES
    mem0_id = Column(Text, nullable=True)  # set on approval
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    decided_at = Column(DateTime(timezone=True), nullable=True)

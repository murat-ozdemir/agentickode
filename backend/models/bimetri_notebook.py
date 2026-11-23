# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 7): the chain notebook of a pull request."""

from sqlalchemy import Column, DateTime, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB

from backend.models.base import Base


class ChainNotebook(Base):
    """Decisions, questions, answers and run outcomes of one PR's agent chain.

    ``entries`` holds ``{kind, text, run_id, at}`` items in time order; ``kind`` is one of
    ``decision``, ``question``, ``answer`` (kept for good), ``run`` or ``ci`` (only the last
    few stay). See ``backend/worker/phases/_bimetri_notebook.py``.
    """

    __tablename__ = "bimetri_chain_notebooks"
    __table_args__ = (UniqueConstraint("project_id", "pr_number"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Text, nullable=False)
    pr_number = Column(Integer, nullable=False)
    entries = Column(JSONB, nullable=False, default=list)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

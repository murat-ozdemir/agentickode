# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: OpenAI API credits entered by hand and daily spend from the Costs API."""

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, func

from backend.models.base import Base


class OpenAICredit(Base):
    """Money loaded on the OpenAI account; the first entry is the balance at that time."""

    __tablename__ = "bimetri_openai_credits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    amount_usd = Column(Numeric(12, 2), nullable=False)
    credited_on = Column(Date, nullable=False)  # counted from this UTC day's start
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OpenAIDailyCost(Base):
    """Organization spend of one UTC day, as the Costs API (and the usage page) reports it."""

    __tablename__ = "bimetri_openai_costs"

    day = Column(Date, primary_key=True)
    amount_usd = Column(Numeric(16, 8), nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

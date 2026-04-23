"""
Campaign data models — Pydantic v2.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class CampaignType(str, Enum):
    MARKETING = "marketing"
    PRICING = "pricing"
    EXPANSION = "expansion"
    POLICY = "policy"
    PRODUCT_LAUNCH = "product_launch"
    OTHER = "other"


class CampaignSpec(BaseModel):
    """Structured campaign information extracted by LLM."""

    campaign_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = Field(description="Campaign name")
    campaign_type: CampaignType = Field(description="Type of campaign")
    market: str = Field(description="Target market")
    budget: str = Field(default="", description="Budget estimate")
    timeline: str = Field(default="", description="Campaign timeline")
    stakeholders: List[str] = Field(
        default_factory=list, description="Key stakeholders"
    )
    kpis: List[str] = Field(
        default_factory=list, description="Key performance indicators"
    )
    identified_risks: List[str] = Field(
        default_factory=list, description="Known risks"
    )
    summary: str = Field(default="", description="Brief campaign summary")
    raw_text: str = Field(default="", description="Full extracted text")
    chunks: List[str] = Field(
        default_factory=list, description="Text chunks for KG building"
    )
    created_at: datetime = Field(default_factory=datetime.now)


class CrisisEvent(BaseModel):
    """A crisis event to inject during simulation."""

    name: str
    description: str
    trigger_round: int = Field(ge=1, le=24)
    severity: str = Field(default="medium")  # low, medium, high, critical
    affected_stakeholders: List[str] = Field(default_factory=list)
    news_headline: str = Field(
        default="", description="Breaking news headline for social media post"
    )


class CrisisScenario(BaseModel):
    """A complete crisis scenario with one or more events."""

    scenario_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    description: str
    is_smooth: bool = Field(
        default=False, description="True = no crisis (smooth scenario)"
    )
    events: List[CrisisEvent] = Field(default_factory=list)

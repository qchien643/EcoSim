"""
Agent generation schemas — Pydantic models shared giữa Core và Simulation.

Mục đích: validate LLM output ở bước `/api/sim/prepare` và đảm bảo
profile.json có shape ổn định cho runtime (`apps/simulation/run_simulation.py`).
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, field_validator


MBTI_TYPES: tuple[str, ...] = (
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
)

MBTIType = Literal[
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
]

Gender = Literal["male", "female"]


class EnrichedAgentLLMOutput(BaseModel):
    """Shape mà LLM phải trả về cho mỗi agent trong batch enrichment.

    LLM nhận: raw parquet persona, gender pre-assigned, campaign context.
    LLM trả: persona rewrite 150-200 chữ, bio ngắn, MBTI suy ra từ persona,
    age phù hợp expertise, interests 3-7 keywords.
    """

    id: int = Field(..., description="Index trong batch, 0-based")
    enriched_persona: str = Field(..., min_length=100, max_length=3000)
    bio: str = Field(..., max_length=200)
    age: int = Field(..., ge=18, le=70)
    mbti: str
    interests: List[str] = Field(default_factory=list, max_length=10)

    @field_validator("mbti")
    @classmethod
    def _validate_mbti(cls, v: str) -> str:
        v_up = (v or "").strip().upper()
        if v_up not in MBTI_TYPES:
            raise ValueError(f"Invalid MBTI '{v}' — must be one of 16 types")
        return v_up

    @field_validator("enriched_persona", "bio")
    @classmethod
    def _strip_newlines(cls, v: str) -> str:
        return " ".join((v or "").split())

    @field_validator("interests")
    @classmethod
    def _clean_interests(cls, v: List[str]) -> List[str]:
        out: List[str] = []
        for item in v:
            s = (item or "").strip().lower()
            if s and len(s) <= 40 and s not in out:
                out.append(s)
        return out[:10]


class AgentProfile(BaseModel):
    """Canonical profile schema được ghi vào `data/simulations/{sim_id}/profiles.json`.

    Các field được chia 3 nhóm:
    - Identity:   realname, username, age, gender, mbti, country
    - Narrative:  persona (full), bio (short), original_persona, domains
    - Runtime:    active_hours, activity_level, posting_probability, followers,
                  interests, posts_per_week, daily_hours

    Runtime fields được `run_simulation.py` đọc — đừng đổi tên.
    """

    # Identity
    agent_id: int
    realname: str
    username: str
    age: int
    gender: Gender
    mbti: MBTIType
    country: str = "Vietnam"

    # Narrative
    persona: str
    bio: str = ""
    original_persona: str = ""
    general_domain: str = ""
    specific_domain: str = ""
    interests: List[str] = Field(default_factory=list)

    # Runtime — behavior. Chỉ giữ field có consumer thực tế trong sim:
    # - posts_per_week / daily_hours: gate posting + size feed
    # - activity_level: inject prompt interview LLM context
    # - followers: popularity re-rank trong feed
    # Removed `active_hours` + `posting_probability` (zero consumer trong
    # apps/simulation/run_simulation.py + interest_feed.py — pre-compute dead).
    activity_level: float = Field(0.5, ge=0.0, le=1.0)
    posts_per_week: int = Field(3, ge=0, le=100)
    daily_hours: float = Field(1.5, ge=0.0, le=24.0)
    followers: int = Field(0, ge=0)


class BatchEnrichmentResponse(BaseModel):
    """Wrapper LLM trả về cho batch — list profiles."""

    profiles: List[EnrichedAgentLLMOutput] = Field(default_factory=list)

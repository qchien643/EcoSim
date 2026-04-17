"""
Simulation data models — Agent profiles, sim config, simulation state.
Updated to MiroFish standard: per-agent behavior, time periods, events, rec config.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class SimStatus(str, Enum):
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Agent Profile — OASIS Reddit Compatible ──

class AgentProfile(BaseModel):
    """Agent profile for OASIS Reddit simulation.

    Contains only the 8 fields that OASIS `generate_reddit_agent_graph` reads:
      - username, realname, bio, persona (system prompt)
      - age, gender, mbti, country
    """
    agent_id: int
    username: str = Field(description="Platform username, ASCII-safe, e.g. nguyen_van_an_123")
    realname: str = Field(description="Full Vietnamese name from NamePool, e.g. Nguyễn Văn An")
    bio: str = Field(default="", description="Short bio ≤160 chars")
    persona: str = Field(default="", description="Full persona text — becomes OASIS agent system prompt. Contains name + campaign context.")
    age: int = Field(default=25, ge=18, le=65, description="18-65, realistic for persona")
    gender: str = Field(default="male", description="male|female")
    mbti: str = Field(default="INTJ", description="MBTI personality type")
    country: str = Field(default="Vietnam", description="Always Vietnam")


# ── Time Config (MiroFish Step 03) ──

class TimePeriod(BaseModel):
    """A named time period with activity multiplier."""
    name: str                          # "peak_hours", "working_hours", etc.
    hours: List[int] = Field(default_factory=list)
    multiplier: float = 1.0            # Activity multiplier (×1.5 = 50% more active)
    label: str = ""                    # Display label: "19:00, 20:00, 21:00, 22:00"


class TimeConfig(BaseModel):
    """Simulation time configuration — MiroFish standard."""
    total_simulation_hours: int = Field(default=72, ge=1)
    minutes_per_round: int = Field(default=60, ge=10, le=120)
    total_rounds: int = Field(default=72, ge=1)
    agents_per_round_min: int = Field(default=2, ge=1)
    agents_per_round_max: int = Field(default=10, ge=1)
    peak_hours: List[int] = Field(default_factory=lambda: [19, 20, 21, 22])
    off_peak_hours: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    period_multipliers: List[TimePeriod] = Field(default_factory=lambda: [
        TimePeriod(name="peak_hours",    hours=[19, 20, 21, 22], multiplier=1.5, label="19:00, 20:00, 21:00, 22:00"),
        TimePeriod(name="working_hours", hours=list(range(9, 19)), multiplier=0.7, label="9:00-18:00"),
        TimePeriod(name="morning_hours", hours=[6, 7, 8],        multiplier=0.4, label="6:00-8:00"),
        TimePeriod(name="low_period",    hours=[0, 1, 2, 3, 4, 5], multiplier=0.05, label="0:00-5:00"),
    ])
    time_reasoning: str = ""


# ── Event Config (MiroFish Step 04) ──

class InitialPost(BaseModel):
    """A seed post for simulation activation."""
    content: str
    poster_type: str = ""           # Entity type of poster
    poster_agent_id: Optional[int] = None
    poster_name: str = ""


class EventConfig(BaseModel):
    """Scenario-driven events injected into simulation."""
    initial_posts: List[InitialPost] = Field(default_factory=list)
    hot_topics: List[str] = Field(default_factory=list)
    narrative_direction: str = ""
    event_reasoning: str = ""


# ── Recommendation Algorithm Config (MiroFish Step 03) ──

class RecConfig(BaseModel):
    """Recommendation algorithm configuration for OASIS."""
    rec_type: str = Field(default="reddit", description="twitter | reddit | random")
    timeliness_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    popularity_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    relevance_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    virality_threshold: int = Field(default=10, ge=1)
    echo_chamber_intensity: float = Field(default=0.5, ge=0.0, le=1.0)


# ── Complete Sim Config (MiroFish Step 03-04 combined) ──

class SimConfig(BaseModel):
    """Complete simulation configuration — MiroFish standard."""
    sim_id: str = Field(default_factory=lambda: f"sim_{uuid.uuid4().hex[:6]}")
    campaign_id: str = ""
    num_agents: int = Field(default=10, ge=1, le=10000)
    time_config: TimeConfig = Field(default_factory=TimeConfig)
    event_config: EventConfig = Field(default_factory=EventConfig)
    rec_config: RecConfig = Field(default_factory=RecConfig)
    reasoning: str = ""
    estimated_duration_minutes: int = 0
    status: SimStatus = SimStatus.CREATED
    created_at: datetime = Field(default_factory=datetime.now)


# ── Runtime State (unchanged) ──

class SimState(BaseModel):
    """Runtime simulation state tracking."""
    sim_id: str
    status: SimStatus = SimStatus.CREATED
    campaign_id: str = ""
    num_agents: int = 0
    profiles_path: str = ""
    config_path: str = ""
    crisis_path: str = ""
    output_dir: str = ""
    current_round: int = 0
    total_rounds: int = 24
    created_at: datetime = Field(default_factory=datetime.now)
    error: str = ""

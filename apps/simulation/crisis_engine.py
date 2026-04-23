"""
EcoSim Crisis Injection Engine
==============================
Dynamically inject external events (price changes, PR crises, market shifts)
into the simulation loop. Supports both scheduled (pre-configured) and
real-time (file-based IPC) injection.

Usage:
    from crisis_engine import CrisisEngine, CrisisEvent

    # Scheduled: events loaded from simulation_config.json
    engine = CrisisEngine([CrisisEvent(trigger_round=3, crisis_type="scandal", ...)])

    # Real-time: API writes pending_crisis.json, engine picks it up
    engine.load_pending_events(sim_dir, current_round)
"""
import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

logger = logging.getLogger("ecosim.crisis")


# ── Crisis Type Templates ──
# Pre-defined templates with default affected domains and interest keywords
CRISIS_TEMPLATES = {
    "price_change": {
        "affected_domains": ["pricing", "budget", "shopping"],
        "interest_keywords": ["giá cả", "tăng giá", "ngân sách", "chi phí", "so sánh giá"],
        "default_severity": 0.6,
        "default_sentiment_shift": "negative",
    },
    "scandal": {
        "affected_domains": ["trust", "privacy", "safety"],
        "interest_keywords": ["bê bối", "rò rỉ", "tin tức nóng", "cảnh báo", "an toàn"],
        "default_severity": 0.8,
        "default_sentiment_shift": "negative",
    },
    "news": {
        "affected_domains": ["technology", "innovation", "competition"],
        "interest_keywords": ["tin mới", "cập nhật", "ra mắt", "đổi mới"],
        "default_severity": 0.5,
        "default_sentiment_shift": "mixed",
    },
    "competitor": {
        "affected_domains": ["competition", "pricing", "alternatives"],
        "interest_keywords": ["đối thủ", "so sánh", "lựa chọn thay thế", "flash sale"],
        "default_severity": 0.6,
        "default_sentiment_shift": "mixed",
    },
    "regulation": {
        "affected_domains": ["policy", "compliance", "government"],
        "interest_keywords": ["quy định", "chính sách", "pháp luật", "tuân thủ"],
        "default_severity": 0.7,
        "default_sentiment_shift": "negative",
    },
    "positive_event": {
        "affected_domains": ["promotion", "reward", "community"],
        "interest_keywords": ["khuyến mãi", "giảm giá", "phần thưởng", "ưu đãi"],
        "default_severity": 0.5,
        "default_sentiment_shift": "positive",
    },
    "custom": {
        "affected_domains": [],
        "interest_keywords": [],
        "default_severity": 0.5,
        "default_sentiment_shift": "negative",
    },
}


@dataclass
class CrisisEvent:
    """A single crisis event to be injected into the simulation."""
    trigger_round: int
    crisis_type: str = "custom"
    title: str = "Crisis Event"
    description: str = ""
    severity: float = 0.5            # 0.0 (mild) → 1.0 (catastrophic)
    affected_domains: List[str] = field(default_factory=list)
    sentiment_shift: str = "negative"  # "negative" | "positive" | "mixed"
    interest_keywords: List[str] = field(default_factory=list)
    crisis_id: str = field(default_factory=lambda: f"crisis_{uuid.uuid4().hex[:8]}")
    injected: bool = False           # True after this event has been processed

    def __post_init__(self):
        # Clamp severity
        self.severity = max(0.0, min(1.0, self.severity))

        # Fill defaults from template if crisis_type is known
        template = CRISIS_TEMPLATES.get(self.crisis_type, CRISIS_TEMPLATES["custom"])
        if not self.affected_domains:
            self.affected_domains = list(template["affected_domains"])
        if not self.interest_keywords:
            self.interest_keywords = list(template["interest_keywords"])
        if self.severity == 0.5 and self.crisis_type != "custom":
            self.severity = template["default_severity"]
        if self.sentiment_shift == "negative" and self.crisis_type != "custom":
            self.sentiment_shift = template["default_sentiment_shift"]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CrisisEvent":
        # Filter to only known fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class CrisisEngine:
    """
    Orchestrates crisis injection into the simulation loop.

    Lifecycle:
        1. __init__: loads scheduled events from config
        2. Each round: get_events_for_round() → returns events to trigger
        3. For each event:
           a. generate_crisis_post() → LLM writes breaking news content
           b. get_interest_perturbation() → keywords + weights for interest drift
           c. get_persona_modifier() → text appended to agent persona prompts
        4. Real-time: load_pending_events() reads file written by API
    """

    def __init__(self, events: Optional[List[CrisisEvent]] = None):
        self.events: List[CrisisEvent] = events or []
        self.triggered_log: List[dict] = []  # history of triggered events
        logger.info(f"CrisisEngine initialized with {len(self.events)} scheduled events")

    def add_event(self, event: CrisisEvent):
        """Add an event (used for real-time injection)."""
        self.events.append(event)
        logger.info(f"Crisis event added: {event.title} (round={event.trigger_round})")

    def get_events_for_round(self, round_num: int) -> List[CrisisEvent]:
        """Return all events scheduled for this round that haven't been injected yet."""
        triggered = []
        for event in self.events:
            if event.trigger_round == round_num and not event.injected:
                event.injected = True
                triggered.append(event)
                self.triggered_log.append({
                    "crisis_id": event.crisis_id,
                    "round": round_num,
                    "title": event.title,
                    "type": event.crisis_type,
                    "severity": event.severity,
                })
        return triggered

    def load_pending_events(self, sim_dir: str, current_round: int) -> List[CrisisEvent]:
        """
        Check for real-time injected events via file-based IPC.
        
        The API writes `pending_crisis.json` into the sim directory.
        This method reads it, creates CrisisEvent objects set to trigger
        at current_round, and deletes the file to prevent re-processing.
        
        Returns list of newly loaded events.
        """
        pending_path = os.path.join(sim_dir, "pending_crisis.json")
        if not os.path.exists(pending_path):
            return []

        loaded = []
        try:
            with open(pending_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Support both single event dict and list of events
            if isinstance(data, dict):
                data = [data]

            for item in data:
                item["trigger_round"] = current_round  # trigger NOW
                event = CrisisEvent.from_dict(item)
                self.add_event(event)
                loaded.append(event)

            # Remove the file after successful read
            os.remove(pending_path)
            logger.info(f"Loaded {len(loaded)} pending crisis events from {pending_path}")

        except Exception as e:
            logger.error(f"Failed to load pending crisis events: {e}")
            # Don't delete on error — let it retry next round
        
        return loaded

    async def generate_crisis_post(self, event: CrisisEvent, agent_model) -> str:
        """
        Use LLM to generate a "breaking news" social media post for the crisis.
        This post gets injected into the platform for agents to discover in their feed.
        """
        try:
            from camel.agents import ChatAgent
            from camel.messages import BaseMessage as BM

            sys_msg = BM.make_assistant_message(
                role_name="News Reporter",
                content=(
                    "You are a news reporter breaking a story on social media. "
                    "Write a SHORT, urgent social media post (3-5 sentences) about "
                    "a breaking event. Make it feel authentic and newsworthy. "
                    "Write in English. Include enough detail to spark discussion."
                ),
            )
            agent = ChatAgent(system_message=sys_msg, model=agent_model)

            prompt = (
                f"Breaking event: {event.title}\n"
                f"Details: {event.description}\n"
                f"Severity: {'Critical' if event.severity > 0.7 else 'Moderate' if event.severity > 0.4 else 'Minor'}\n"
                f"Areas affected: {', '.join(event.affected_domains)}\n\n"
                f"Write a breaking news social media post about this."
            )
            user_msg = BM.make_user_message(role_name="Editor", content=prompt)
            resp = await agent.astep(user_msg)
            content = resp.msgs[0].content.strip() if resp.msgs else ""
            
            # Clean up quotes
            if content.startswith('"') and content.endswith('"'):
                content = content[1:-1]
            
            return content if len(content) > 10 else f"BREAKING: {event.title}. {event.description}"

        except Exception as e:
            logger.warning(f"LLM crisis post generation failed: {e}")
            # Fallback: use raw title + description
            return f"⚠️ BREAKING: {event.title}. {event.description}"

    def get_interest_perturbation(self, event: CrisisEvent) -> dict:
        """
        Return interest perturbation parameters for InterestVectorTracker.
        
        Higher severity → stronger perturbation:
        - weight_boost: how much weight to give crisis keywords (0.3-1.0)
        - decay_factor: how much to suppress existing interests (0.0-0.5)
        - keywords: crisis-related keywords to inject
        """
        weight_boost = 0.3 + (event.severity * 0.7)  # 0.3→1.0 based on severity
        decay_factor = event.severity * 0.3            # 0.0→0.3 based on severity

        # Combine event-specific keywords with template keywords
        keywords = list(event.interest_keywords)
        # Add title words as extra keywords
        title_words = [w for w in event.title.split() if len(w) > 3]
        keywords.extend(title_words[:3])
        # Deduplicate
        keywords = list(dict.fromkeys(keywords))

        return {
            "keywords": keywords,
            "weight_boost": round(weight_boost, 2),
            "decay_factor": round(decay_factor, 2),
            "source": f"crisis:{event.crisis_id}",
        }

    def get_persona_modifier(self, event: CrisisEvent) -> str:
        """
        Return text to append to agent persona during crisis round(s).
        This makes LLM-generated posts/comments naturally reference the crisis.
        """
        severity_label = (
            "extremely concerned about"
            if event.severity > 0.7
            else "aware of" if event.severity > 0.4
            else "has heard about"
        )

        sentiment_label = {
            "negative": "worried and skeptical",
            "positive": "excited and optimistic",
            "mixed": "curious but uncertain",
        }.get(event.sentiment_shift, "curious")

        modifier = (
            f"You just learned about: {event.title}. {event.description} "
            f"You are {severity_label} this development and feeling {sentiment_label}. "
            f"This may influence what you post or comment about."
        )
        return modifier

    def get_crisis_log(self) -> List[dict]:
        """Return history of all triggered crisis events (for reporting)."""
        return list(self.triggered_log)

    def has_pending_events(self) -> bool:
        """Check if there are future un-injected events."""
        return any(not e.injected for e in self.events)

    def get_summary(self) -> dict:
        """Summary for progress/status reporting."""
        return {
            "total_events": len(self.events),
            "triggered": len(self.triggered_log),
            "pending": sum(1 for e in self.events if not e.injected),
            "log": self.triggered_log,
        }

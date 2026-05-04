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
from typing import List, Optional

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
    """A single crisis event injected into the simulation.

    One-shot: fires at `trigger_round`. Keywords are NOT user input nor
    template-filled — `CrisisEngine.extract_keywords()` calls an LLM at
    trigger time using title + description + affected_domains + sentiment
    to produce N high-quality phrases for vector search. Those phrases get
    written into `interest_keywords` (output, post-extraction) and injected
    into every agent's interest vector with weight = severity. Longevity is
    owned by `InterestVectorTracker.update_after_round`.
    """
    trigger_round: int
    crisis_type: str = "custom"
    title: str = "Crisis Event"
    description: str = ""
    severity: float = 0.5            # 0.0 (mild) → 1.0 (catastrophic)
    affected_domains: List[str] = field(default_factory=list)
    sentiment_shift: str = "negative"  # "negative" | "positive" | "mixed"
    # `interest_keywords` is now an OUTPUT field. UI no longer accepts it.
    # Populated by `CrisisEngine.extract_keywords()` at trigger time and
    # kept in the dataclass for audit/UI display after the sim runs.
    interest_keywords: List[str] = field(default_factory=list)
    # How many keyphrases the LLM should extract — UI-tunable, default 5.
    n_keywords: int = 5
    crisis_id: str = field(default_factory=lambda: f"crisis_{uuid.uuid4().hex[:8]}")
    injected: bool = False           # True after one-shot side effects fired

    def __post_init__(self):
        # Clamp severity to [0.0, 1.0].
        self.severity = max(0.0, min(1.0, self.severity))
        # Defensive clamp on n_keywords (1..20) — UI also clamps but server
        # should never trust the client.
        self.n_keywords = max(1, min(20, int(self.n_keywords)))

        # Fill empty `affected_domains` from template (provides LLM context
        # at extraction time). `interest_keywords` is NOT auto-filled — the
        # LLM produces those at trigger time.
        template = CRISIS_TEMPLATES.get(self.crisis_type, CRISIS_TEMPLATES["custom"])
        if not self.affected_domains:
            self.affected_domains = list(template["affected_domains"])

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
        2. Each round: get_events_for_round() → events that fire this round
        3. For each event (one-shot at trigger_round):
           a. generate_crisis_post() → LLM writes breaking news content
           b. extract_keywords() → LLM extracts N keyphrases for vector search
           c. caller injects those keywords into every agent's interest vector
              with weight = severity (no per-agent scaling — flat)
           d. get_persona_modifier() → text appended to agent persona prompts
           e. get_short_directive() → imperative line at end of LLM prompt
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
        """Return events scheduled for this round that haven't triggered yet.

        Crisis is one-shot: fires only at `trigger_round`. After the trigger,
        the persistent effect is carried by each agent's interest vector
        (keywords decay/boost via `update_after_round`). No persistence
        window is tracked here — agent traits + engagement decide longevity.
        """
        triggered: List[CrisisEvent] = []
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

    async def extract_keywords(
        self, event: CrisisEvent, agent_model, n: int
    ) -> List[str]:
        """Extract N keyphrases from a crisis via LLM, ready for vector search
        injection into agent interest vectors.

        Output: lowercase phrases, no punctuation, deduped, capped at N.
        These match `InterestVectorTracker.update_after_round`'s substring
        matching: a comment containing `"tiki"` will boost an interest item
        whose key is also `"tiki"` (exact lowercase, no punctuation).

        Returns `[]` on LLM failure — caller should skip the inject step.
        """
        n = max(1, min(20, int(n)))
        try:
            from camel.agents import ChatAgent
            from camel.messages import BaseMessage as BM

            sys_msg = BM.make_assistant_message(
                role_name="Keyword Extractor",
                content=(
                    "You extract concise keyphrases from a breaking news "
                    "event. Output ONLY a JSON array of N lowercase phrases "
                    "— no punctuation, no leading/trailing whitespace, no "
                    "duplicates. Each phrase is a 1-3 word keyphrase suitable "
                    "for matching social media content. Match the language "
                    "of the input (Vietnamese in/Vietnamese out, English in/"
                    "English out). Brand names and proper nouns are kept as-is "
                    "(e.g. 'tiki', 'shopee'). Avoid stopwords."
                ),
            )
            domains = (
                ", ".join(event.affected_domains)
                if event.affected_domains else "(none)"
            )
            prompt = (
                f"Event title: {event.title}\n"
                f"Description: {event.description or '(none)'}\n"
                f"Affected domains: {domains}\n"
                f"Sentiment: {event.sentiment_shift}\n\n"
                f'Extract exactly {n} keyphrases as JSON: '
                f'["phrase1", "phrase2", ...]'
            )
            user_msg = BM.make_user_message(role_name="User", content=prompt)
            agent = ChatAgent(system_message=sys_msg, model=agent_model)
            resp = await agent.astep(user_msg)
            raw = resp.msgs[0].content.strip() if resp.msgs else "[]"
        except Exception as e:
            logger.warning("Crisis extract_keywords: LLM call failed: %s", e)
            return []

        # Strip code fences if LLM wraps in ```json ... ```
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Crisis extract_keywords: LLM returned non-JSON: %r",
                raw[:120],
            )
            return []

        if not isinstance(parsed, list):
            logger.warning(
                "Crisis extract_keywords: expected list, got %s",
                type(parsed).__name__,
            )
            return []

        # Sanitize: lowercase, strip ALL punctuation (internal too — apostrophe
        # in "shopee's", hyphen in "flash-sale" → space split), dedup
        # case-insensitively, cap to N. Result: lowercase phrases of 1-3 word
        # tokens ready for `kw in engaged_lower` substring match in
        # InterestVectorTracker.update_after_round.
        import re as _re
        cleaned: List[str] = []
        seen: set = set()
        for k in parsed:
            s = str(k).lower()
            # Replace any non-word/non-whitespace char with a space so
            # "shopee's" → "shopee s", "flash-sale" → "flash sale". Keep
            # alphanumerics + Vietnamese diacritics (\w covers them).
            s = _re.sub(r"[^\w\s]", " ", s, flags=_re.UNICODE)
            # Drop tokens shorter than 2 chars (stray "s", "a", ...)
            tokens = [t for t in s.split() if len(t) >= 2]
            phrase = " ".join(tokens)
            if phrase and phrase not in seen:
                seen.add(phrase)
                cleaned.append(phrase)
            if len(cleaned) >= n:
                break
        return cleaned

    async def select_relevant_keywords(
        self,
        event: CrisisEvent,
        candidate_keywords: List[str],
        campaign_info: dict,
        agent_model,
        n: int,
    ) -> List[str]:
        """Filter the candidate pool down to N keywords with the highest
        potential impact on the current campaign.

        Two-LLM pipeline: `extract_keywords` produces a wide pool (typically
        2*N), then this method asks an "impact analyst" persona to pick the
        N keywords most likely to land on this campaign — based on
        campaign name + market + summary. The LLM is told to copy keywords
        verbatim from the candidate list; we strictly whitelist its output
        against the input pool to defend against hallucination/rephrasing.

        Fallback: if the LLM call fails, the JSON parse fails, or the
        whitelist filter produces nothing, return `candidate_keywords[:n]`
        — order-preserving truncation, never crash.

        Args:
            event: Crisis event (used for context in prompt).
            candidate_keywords: Output of `extract_keywords`.
            campaign_info: Dict with `name`, `market`, `summary` keys.
            agent_model: Camel-ai model instance.
            n: Target output size. If `len(candidate_keywords) <= n`, return
               the input as-is (no LLM call needed).
        """
        if not candidate_keywords:
            return []
        n = max(1, min(20, int(n)))
        if len(candidate_keywords) <= n:
            return list(candidate_keywords)

        try:
            from camel.agents import ChatAgent
            from camel.messages import BaseMessage as BM

            sys_msg = BM.make_assistant_message(
                role_name="Impact Analyst",
                content=(
                    "You are a campaign analyst. Given candidate crisis "
                    "keywords and a target marketing campaign, select the N "
                    "keywords with HIGHEST potential impact on this specific "
                    "campaign. Consider brand association, market overlap, "
                    "audience intersection, and competitive dynamics. "
                    "Output ONLY a JSON array of N selected keywords copied "
                    "VERBATIM from the candidates list, ordered by impact "
                    "(highest first). Do NOT invent new keywords."
                ),
            )
            prompt = (
                f"Crisis title: {event.title}\n"
                f"Crisis description: {event.description or '(none)'}\n\n"
                f"Campaign name: {campaign_info.get('name') or '(unknown)'}\n"
                f"Campaign market: {campaign_info.get('market') or '(unknown)'}\n"
                f"Campaign summary: {campaign_info.get('summary') or '(unknown)'}\n\n"
                f"Candidate keywords (choose ONLY from these):\n"
                f"{json.dumps(candidate_keywords, ensure_ascii=False)}\n\n"
                f'Select top {n} as JSON: ["kw1", "kw2", ...]'
            )
            user_msg = BM.make_user_message(role_name="User", content=prompt)
            agent = ChatAgent(system_message=sys_msg, model=agent_model)
            resp = await agent.astep(user_msg)
            raw = resp.msgs[0].content.strip() if resp.msgs else "[]"
        except Exception as e:
            logger.warning(
                "select_relevant_keywords: LLM call failed: %s — fallback "
                "to first %d candidates", e, n,
            )
            return list(candidate_keywords[:n])

        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "select_relevant_keywords: non-JSON output %r — fallback",
                raw[:120],
            )
            return list(candidate_keywords[:n])

        if not isinstance(parsed, list):
            logger.warning(
                "select_relevant_keywords: expected list, got %s — fallback",
                type(parsed).__name__,
            )
            return list(candidate_keywords[:n])

        # Strict whitelist: LLM output must be a subset of the candidate
        # pool. Lowercase-compare so "Tiki" → "tiki" matches if extract
        # already lowercased its output (which it does).
        candidates_set = set(candidate_keywords)
        selected: List[str] = []
        seen: set = set()
        for k in parsed:
            s = str(k).strip().lower()
            if s in candidates_set and s not in seen:
                seen.add(s)
                selected.append(s)
            if len(selected) >= n:
                break

        # All hallucinations / empty result → fallback
        if not selected:
            return list(candidate_keywords[:n])

        # Top up from remaining candidates (preserve original order) if LLM
        # picked fewer than N
        if len(selected) < n:
            for k in candidate_keywords:
                if k not in seen:
                    selected.append(k)
                    seen.add(k)
                    if len(selected) >= n:
                        break

        return selected

    @staticmethod
    def resolve_author_id(
        strategy: str,
        profiles: List[dict],
        default_id: int = 0,
    ) -> int:
        """Chọn agent_id để làm tác giả breaking news post.

        Strategies:
        - ``"agent_0"`` (default): hardcode agent 0.
        - ``"influencer"``: agent có `followers` cao nhất.
        - ``"system"``: alias cho agent 0 (ecosystem chưa có system user riêng).
        """
        strategy = (strategy or "agent_0").lower()
        if not profiles:
            return default_id
        if strategy == "influencer":
            best_id = default_id
            best_followers = -1
            for aid, p in enumerate(profiles):
                f = int(p.get("followers", 0) or 0)
                if f > best_followers:
                    best_followers = f
                    best_id = aid
            return best_id
        # "agent_0" | "system" | unknown → agent 0
        return default_id

    def get_persona_modifier(self, event: CrisisEvent) -> str:
        """
        Return text to append to agent persona during crisis round(s).

        Imperative phrasing: instead of the older passive *"This may influence
        what you post"* (which the LLM ignored — observed in sim_da2b8fb2
        where 0/47 comments and 0/6 organic posts mentioned the crisis), we
        now tell the agent it should reference or react to the event.
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
            f"You should reference or react to this event when posting or "
            f"commenting — share your concrete reaction (concern, defense, "
            f"skepticism, or opinion), not generic engagement."
        )
        return modifier

    def get_short_directive(self, event: CrisisEvent) -> str:
        """One-line directive placed at the END of the LLM prompt at the
        trigger round only. Subsequent rounds rely on the perturbed interest
        vector + persona memory to keep crisis salience alive.

        Empirically the LLM follows the last instruction in the user message
        most strongly, so we move the imperative there.
        """
        desc = (event.description or "").strip()
        snippet = desc[:200] + ("…" if len(desc) > 200 else "") if desc else ""
        body = f"⚠️ Active event: {event.title}."
        if snippet:
            body += f" {snippet}"
        body += (
            " Your post/comment should reference this event — share a "
            "concrete reaction (concern / skepticism / defense / opinion), "
            "not generic engagement like 'sounds exciting' or "
            "'can't wait to see'."
        )
        return body

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

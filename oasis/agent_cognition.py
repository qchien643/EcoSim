"""
Agent Cognitive Layer — Memory, Reflection, Interest Evolution, MBTI Modifiers.

Phase 1: AgentMemory (round-by-round memory buffer)
Phase 2: MBTI Behavioral Modifiers
Phase 3: InterestTracker (planned)
Phase 4: AgentReflection (planned)

Reference papers:
- RecAgent (ACL 2024): sensory → short-term → long-term memory
- Generative Agents (Stanford): 3-factor retrieval (recency × importance × relevance)
- S3 (Tsinghua): perception → attitude drift → interest evolution
- Agent4Rec: factual + emotional memory, emotion-driven reflection
"""
from collections import defaultdict, deque
from typing import Dict, List, Optional


# ══════════════════════════════════════════════════════════════
# Phase 1: Agent Memory
# ══════════════════════════════════════════════════════════════

class AgentMemory:
    """Lightweight round-by-round memory buffer per agent.

    Each round, raw actions (post, comment, like) are recorded.
    At round end, they are flushed into a 1-line summary stored
    in a FIFO buffer (max MAX_BUFFER rounds).

    The summary is injected into LLM prompts so agents "remember"
    what they did recently.

    Reference: RecAgent — sensory → short-term memory layer.
    """

    MAX_BUFFER = 5  # Keep last 5 round summaries

    def __init__(self, num_agents: int):
        # agent_id → deque of round summary strings
        self._buffers: Dict[int, deque] = defaultdict(
            lambda: deque(maxlen=self.MAX_BUFFER)
        )
        # agent_id → list of raw actions this round (sensory)
        self._current_round: Dict[int, list] = defaultdict(list)

    def record_action(self, agent_id: int, action_type: str,
                      content_preview: str = ""):
        """Record a raw action in this round (sensory memory).

        Args:
            agent_id: The agent who performed the action.
            action_type: One of 'create_post', 'create_comment', 'like_post'.
            content_preview: Short preview of content (truncated to 100 chars).
        """
        self._current_round[agent_id].append({
            "action": action_type,
            "preview": content_preview[:100] if content_preview else "",
        })

    def end_round(self, round_num: int):
        """Flush current round actions into short-term summary.

        Converts raw actions into a readable string like:
        "Round 3: posted 'Excited about deals!'; liked a post; commented 'Great update'"
        """
        for agent_id, actions in self._current_round.items():
            if not actions:
                continue
            parts = []
            for a in actions:
                atype = a["action"]
                preview = a["preview"]
                if atype == "create_post":
                    snippet = f'"{preview[:60]}"' if preview else ""
                    parts.append(f"posted {snippet}".strip())
                elif atype == "create_comment":
                    snippet = f'"{preview[:60]}"' if preview else ""
                    parts.append(f"commented {snippet}".strip())
                elif atype == "like_post":
                    parts.append("liked a post")
                elif atype == "repost":
                    parts.append("shared a post")
                elif atype == "follow":
                    parts.append("followed someone")
                else:
                    parts.append(atype)
            summary = f"Round {round_num}: " + "; ".join(parts)
            self._buffers[agent_id].append(summary)
        self._current_round.clear()

    def get_context(self, agent_id: int) -> str:
        """Get recent memory context string for LLM prompt injection.

        Returns empty string if agent has no memory yet (first round).
        Otherwise returns a multi-line block like:
            Your recent activity:
            Round 1: posted "Hello world"; liked a post
            Round 2: commented "Great insight"
        """
        buffer = self._buffers.get(agent_id)
        if not buffer:
            return ""
        return "Your recent activity:\n" + "\n".join(buffer)

    def get_round_count(self, agent_id: int) -> int:
        """Get how many rounds are stored for this agent."""
        buffer = self._buffers.get(agent_id)
        return len(buffer) if buffer else 0


# ══════════════════════════════════════════════════════════════
# Phase 2: MBTI Behavioral Modifiers
# ══════════════════════════════════════════════════════════════

# MBTI dimension → behavioral multiplier mapping.
# Reference: Agent4Rec (activity level + conformity dimensions)
#
# E/I: Extraversion → higher post/comment frequency
# F/T: Feeling → higher emotional engagement (likes)
# P/J: Perceiving → wider feed exploration
# N/S: Intuition → deeper reflection (used in Phase 4)

_MBTI_DIMENSION_MODIFIERS = {
    # Extraversion vs Introversion → posting + commenting frequency
    "E": {"post_mult": 1.2, "comment_mult": 1.3},
    "I": {"post_mult": 0.8, "comment_mult": 0.7},

    # Feeling vs Thinking → engagement intensity (liking)
    "F": {"like_mult": 1.2},
    "T": {"like_mult": 0.9},

    # Perceiving vs Judging → feed exploration breadth
    "P": {"feed_mult": 1.2},
    "J": {"feed_mult": 0.9},

    # iNtuition vs Sensing → reflection boost (Phase 4)
    "N": {"reflection_boost": 1.3},
    "S": {"reflection_boost": 0.8},
}

# Default values when MBTI is unknown or feature is disabled
_DEFAULT_MODIFIERS = {
    "post_mult": 1.0,
    "comment_mult": 1.0,
    "like_mult": 1.0,
    "feed_mult": 1.0,
    "reflection_boost": 1.0,
}


def get_behavior_modifiers(mbti: str) -> dict:
    """Compute agent-specific behavior multipliers from MBTI type.

    Args:
        mbti: 4-letter MBTI string (e.g. "ENFJ", "ISTP").
              If empty or invalid, returns all-1.0 defaults.

    Returns:
        Dict with keys: post_mult, comment_mult, like_mult,
        feed_mult, reflection_boost. All default to 1.0.

    Example:
        >>> get_behavior_modifiers("ENFJ")
        {'post_mult': 1.2, 'comment_mult': 1.3, 'like_mult': 1.2,
         'feed_mult': 0.9, 'reflection_boost': 1.3}
    """
    result = dict(_DEFAULT_MODIFIERS)
    for char in mbti.upper():
        mods = _MBTI_DIMENSION_MODIFIERS.get(char, {})
        for key, val in mods.items():
            if key in result:
                result[key] = val
    return result


# ══════════════════════════════════════════════════════════════
# Phase 3: Interest Drift — Weighted Interest Vector
# ══════════════════════════════════════════════════════════════

# Stopwords for keyword extraction (lightweight, no nltk needed)
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "and", "but", "or", "nor", "not", "so", "yet",
    "both", "either", "neither", "each", "every", "all", "any", "few",
    "more", "most", "other", "some", "such", "no", "only", "own", "same",
    "than", "too", "very", "just", "about", "above", "below", "between",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "they", "them", "their", "this", "that", "these", "those", "what",
    "which", "who", "whom", "how", "when", "where", "why", "if", "then",
    "here", "there", "up", "out", "also", "like", "really", "great",
    "good", "much", "many", "well", "think", "know", "get", "got",
    "make", "go", "see", "say", "said", "one", "two", "new", "post",
})


class CognitiveTraits:
    """Per-agent cognitive personality that controls interest evolution.

    Each agent gets unique traits derived from their MBTI type. These
    traits determine HOW FAST and HOW DEEPLY interests change.

    User-facing names (Vietnamese):
    - conviction → Độ bảo thủ
    - forgetfulness → Độ hay quên
    - curiosity → Độ tò mò
    - impressionability → Độ dễ bị ảnh hưởng
    """

    __slots__ = ('conviction', 'forgetfulness', 'curiosity', 'impressionability')

    def __init__(self, conviction: float = 0.6, forgetfulness: float = 0.15,
                 curiosity: float = 0.3, impressionability: float = 0.15):
        self.conviction = max(0.1, min(1.0, conviction))
        self.forgetfulness = max(0.05, min(0.3, forgetfulness))
        self.curiosity = max(0.1, min(0.5, curiosity))
        self.impressionability = max(0.05, min(0.3, impressionability))

    def to_dict(self) -> dict:
        return {
            "conviction": round(self.conviction, 2),
            "forgetfulness": round(self.forgetfulness, 2),
            "curiosity": round(self.curiosity, 2),
            "impressionability": round(self.impressionability, 2),
        }

    def describe(self) -> str:
        """Human-readable description of traits."""
        lines = []
        # Conviction
        if self.conviction >= 0.7:
            lines.append(f"Độ bảo thủ: {self.conviction:.2f} — Giữ sở thích lâu")
        elif self.conviction <= 0.4:
            lines.append(f"Độ bảo thủ: {self.conviction:.2f} — Dễ thay đổi sở thích")
        else:
            lines.append(f"Độ bảo thủ: {self.conviction:.2f} — Trung bình")

        # Forgetfulness
        if self.forgetfulness >= 0.2:
            lines.append(f"Độ hay quên: {self.forgetfulness:.2f} — Quên nhanh sở thích cũ")
        elif self.forgetfulness <= 0.1:
            lines.append(f"Độ hay quên: {self.forgetfulness:.2f} — Nhớ lâu")
        else:
            lines.append(f"Độ hay quên: {self.forgetfulness:.2f} — Trung bình")

        # Curiosity
        if self.curiosity >= 0.4:
            lines.append(f"Độ tò mò: {self.curiosity:.2f} — Rất thích khám phá")
        elif self.curiosity <= 0.2:
            lines.append(f"Độ tò mò: {self.curiosity:.2f} — Ít khám phá cái mới")
        else:
            lines.append(f"Độ tò mò: {self.curiosity:.2f} — Trung bình")

        # Impressionability
        if self.impressionability >= 0.2:
            lines.append(f"Độ dễ bị ảnh hưởng: {self.impressionability:.2f} — Dễ thuyết phục")
        elif self.impressionability <= 0.1:
            lines.append(f"Độ dễ bị ảnh hưởng: {self.impressionability:.2f} — Khó thuyết phục")
        else:
            lines.append(f"Độ dễ bị ảnh hưởng: {self.impressionability:.2f} — Trung bình")

        return "\n".join(lines)


# MBTI → Cognitive Traits mapping
# J/P → conviction + curiosity
# S/N → forgetfulness
# F/T → impressionability
# E/I → curiosity bonus
_MBTI_COGNITIVE_MAP = {
    "J": {"conviction": 0.80, "curiosity": 0.20},
    "P": {"conviction": 0.40, "curiosity": 0.45},
    "S": {"forgetfulness": 0.10},
    "N": {"forgetfulness": 0.20},
    "F": {"impressionability": 0.25},
    "T": {"impressionability": 0.10},
    "E": {"curiosity_bonus": 0.10},
    "I": {"curiosity_bonus": -0.05},
}

_DEFAULT_TRAITS = {"conviction": 0.6, "forgetfulness": 0.15,
                   "curiosity": 0.30, "impressionability": 0.15}


def get_cognitive_traits(mbti: str) -> CognitiveTraits:
    """Derive cognitive personality traits from MBTI type.

    Args:
        mbti: 4-letter MBTI string. If empty, returns default traits.

    Returns:
        CognitiveTraits instance with values influenced by MBTI.
    """
    vals = dict(_DEFAULT_TRAITS)
    curiosity_bonus = 0.0
    for char in mbti.upper():
        mods = _MBTI_COGNITIVE_MAP.get(char, {})
        for key, val in mods.items():
            if key == "curiosity_bonus":
                curiosity_bonus = val
            elif key in vals:
                vals[key] = val
    vals["curiosity"] = max(0.1, min(0.5, vals["curiosity"] + curiosity_bonus))
    return CognitiveTraits(**vals)

# ── KeyBERT-based Keyphrase Extraction ──
# Singleton: initialized once, reuses all-MiniLM-L6-v2 from ChromaDB
_keybert_model = None
_keybert_available = None


def _get_keybert():
    """Lazy-init KeyBERT singleton, reusing all-MiniLM-L6-v2."""
    global _keybert_model, _keybert_available
    if _keybert_available is False:
        return None
    if _keybert_model is not None:
        return _keybert_model
    try:
        from keybert import KeyBERT
        from sentence_transformers import SentenceTransformer
        # Explicitly create ST model to avoid modality detection issues
        # with sentence-transformers v5.x+
        st_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        _keybert_model = KeyBERT(model=st_model)
        _keybert_available = True
        return _keybert_model
    except ImportError:
        _keybert_available = False
        print("[COGNITION] KeyBERT not installed, using N-gram fallback")
        return None
    except Exception as e:
        _keybert_available = False
        print(f"[COGNITION] KeyBERT init failed: {e}")
        return None


def _clean_social_text(text: str) -> str:
    """Clean social media text before keyphrase extraction."""
    import re
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    # Remove mentions @username
    text = re.sub(r'@\w+', '', text)
    # Remove hashtag symbols (keep the word)
    text = text.replace('#', '')
    # Remove emojis (unicode emoji ranges)
    text = re.sub(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
        r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
        r'\U00002700-\U000027BF\U0001F900-\U0001F9FF'
        r'\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF'
        r'\U00002600-\U000026FF]+', ' ', text
    )
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_keyphrases(text: str, max_phrases: int = 3) -> List[str]:
    """Extract meaningful keyphrases from text using KeyBERT.

    Uses semantic similarity between full document embedding and
    candidate N-gram embeddings (same all-MiniLM-L6-v2 model as ChromaDB).

    MMR diversification ensures extracted phrases are distinct topics,
    not redundant variations of the same keyword.

    Falls back to simple N-gram extraction if KeyBERT unavailable.

    Args:
        text: Raw post/comment content.
        max_phrases: Max keyphrases to return.

    Returns:
        List of lowercase keyphrase strings.

    Example:
        "Shopee Black Friday Sale! Amazing deals on electronics"
        → ["black friday sale", "shopee electronics", "deals"]
    """
    if not text or len(text.strip()) < 10:
        return []

    cleaned = _clean_social_text(text)
    if len(cleaned) < 10:
        return []

    # Try KeyBERT first
    kw_model = _get_keybert()
    if kw_model is not None:
        try:
            # Request more candidates, then filter
            keywords = kw_model.extract_keywords(
                cleaned,
                keyphrase_ngram_range=(1, 3),
                stop_words='english',
                use_mmr=True,
                diversity=0.5,
                top_n=max_phrases + 2,  # ask for extras to account for filtering
            )
            # Filter: keep score > 0.05, reject single generic words
            _SINGLE_REJECT = frozenset({
                "join", "sale", "deal", "best", "good", "great", "love",
                "amazing", "check", "make", "find", "look", "come", "let",
                "new", "get", "use", "try", "see", "know", "take", "give",
            })
            result = []
            for kw, score in keywords:
                if score < 0.05:
                    continue
                # Reject single words that are generic/too short
                words_in_kw = kw.split()
                if len(words_in_kw) == 1:
                    if len(kw) < 5 or kw.lower() in _SINGLE_REJECT:
                        continue
                result.append(kw)
                if len(result) >= max_phrases:
                    break
            if result:
                return result
        except Exception as e:
            # Fallback on any KeyBERT error
            pass

    # Fallback: simple content-word extraction (no N-gram noise)
    return _extract_phrases_fallback(cleaned, max_phrases)


def _extract_phrases_fallback(text: str, max_phrases: int = 3) -> List[str]:
    """Lightweight N-gram fallback when KeyBERT is unavailable."""
    if not text:
        return []

    _WEAK_WORDS = frozenset({
        "amazing", "awesome", "check", "today", "yesterday", "tomorrow",
        "look", "love", "hate", "want", "need", "best", "worst", "super",
        "cool", "nice", "guys", "everyone", "people", "things", "stuff",
        "come", "back", "still", "always", "never", "real", "sure",
        "please", "thanks", "thank", "help", "right", "left", "part",
        "kind", "share", "comment", "follow", "click", "link", "free",
        "update", "latest", "full", "total", "done", "lol", "wow",
    })

    tokens = [w.strip(".,!?\"'()[]{}#@:;") for w in text.split()]
    tokens = [t for t in tokens if t]

    # Build content runs
    runs: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        lower = token.lower()
        if (len(lower) > 2 and lower not in _STOPWORDS
                and lower not in _WEAK_WORDS
                and any(c.isalpha() for c in lower)):
            current.append(token)
        else:
            if current:
                runs.append(current)
                current = []
    if current:
        runs.append(current)

    phrases = {}
    for run in runs:
        if len(run) >= 2:
            phrase = " ".join(run[:3]).lower()
            phrases[phrase] = phrases.get(phrase, 0) + len(run)
        elif run and (run[0][0].isupper() and len(run[0]) > 3):
            phrases[run[0].lower()] = 1

    if not phrases:
        freq = {}
        for t in tokens:
            lower = t.lower()
            if len(lower) > 4 and lower not in _STOPWORDS and lower.isalpha():
                freq[lower] = freq.get(lower, 0) + 1
        return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:max_phrases]]

    return [p for p, _ in sorted(phrases.items(), key=lambda x: -x[1])[:max_phrases]]


class InterestItem:
    """A single weighted interest for an agent."""

    __slots__ = ('keyword', 'weight', 'source', 'first_seen',
                 'last_engaged', 'engagement_count')

    def __init__(self, keyword: str, weight: float, source: str,
                 first_seen: int = 0, last_engaged: int = -1):
        self.keyword = keyword
        self.weight = weight
        self.source = source  # "profile" | "drift" | "graph" | "campaign"
        self.first_seen = first_seen
        self.last_engaged = last_engaged
        self.engagement_count = 0

    def to_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "weight": round(self.weight, 3),
            "source": self.source,
            "first_seen": self.first_seen,
            "last_engaged": self.last_engaged,
            "engagement_count": self.engagement_count,
        }


class InterestVectorTracker:
    """Manages weighted interest vectors for all agents.

    Each agent has:
    - CognitiveTraits (from MBTI) controlling evolution speed
    - Dict[str, InterestItem] — current interests with weights
    - history: per-round snapshots for charting

    Per-round update rules:
    1. BOOST: engaged interest → weight += impressionability
    2. DECAY: non-engaged → weight *= (1 - forgetfulness)
    3. FLOOR: profile interests → min weight = conviction * 0.3
    4. NEW: new keywords → initial weight = curiosity
    5. PRUNE: weight < 0.03 and source != "profile" → remove

    Reference: S3 (Tsinghua) — perception → attitude → interest shift.
    """

    MAX_INTERESTS = 10  # Max interests per agent

    def __init__(self):
        self._traits: Dict[int, CognitiveTraits] = {}
        self._vectors: Dict[int, Dict[str, InterestItem]] = {}
        self._history: Dict[int, list] = defaultdict(list)

    def initialize_agent(self, agent_id: int, profile: dict):
        """Create initial interest vector from agent profile.

        Extracts interests from:
        1. profile["interests"] (explicit list, if exists)
        2. profile["specific_domain"] (weight 0.8)
        3. profile["general_domain"] (weight 0.6)
        4. Fallback: first 2 sentences of persona (weight 0.5)

        Cognitive traits derived from MBTI.
        """
        mbti = profile.get("mbti", "")
        self._traits[agent_id] = get_cognitive_traits(mbti)

        items: Dict[str, InterestItem] = {}

        # 1. Explicit interests
        interests = profile.get("interests", [])
        if isinstance(interests, str) and interests:
            interests = [s.strip() for s in interests.split(",") if s.strip()]
        for kw in interests:
            items[kw.lower()] = InterestItem(kw, weight=0.8, source="profile")

        # 2. Specific domain
        spec = profile.get("specific_domain", "")
        if spec and spec.lower() not in items:
            items[spec.lower()] = InterestItem(spec, weight=0.8, source="profile")

        # 3. General domain
        gen = profile.get("general_domain", "")
        if gen and gen.lower() not in items:
            items[gen.lower()] = InterestItem(gen, weight=0.6, source="profile")

        # 4. Fallback: extract keywords from persona
        if not items:
            persona = profile.get("original_persona", "") or profile.get("persona", "")
            if persona:
                words = [w.strip(".,!?\"'()[]{}#@").lower() for w in persona.split()]
                words = [w for w in words if len(w) > 4 and w not in _STOPWORDS and w.isalpha()]
                freq: Dict[str, int] = {}
                for w in words:
                    freq[w] = freq.get(w, 0) + 1
                top = sorted(freq.items(), key=lambda x: -x[1])[:3]
                for word, _ in top:
                    items[word] = InterestItem(word, weight=0.5, source="profile")

        self._vectors[agent_id] = items

        # Save initial snapshot
        self._history[agent_id].append(
            {k: v.weight for k, v in items.items()}
        )

    def update_after_round(self, agent_id: int, round_num: int,
                           engaged_contents: List[str],
                           graph_entities: List[str] = None):
        """Update interest weights after a round based on engagement.

        Args:
            agent_id: Agent who engaged.
            round_num: Current round number.
            engaged_contents: List of post content strings from liked/commented.
            graph_entities: Optional entity names from knowledge graph.
        """
        traits = self._traits.get(agent_id)
        items = self._vectors.get(agent_id)
        if traits is None or items is None:
            return

        # Extract meaningful keyphrases from engaged content (KeyBERT)
        engaged_keywords = set()
        if engaged_contents:
            for content in engaged_contents:
                phrases = _extract_keyphrases(content)
                engaged_keywords.update(phrases[:2])  # Top 2 phrases per post

        # Also check if existing interests match engaged content
        engaged_lower = " ".join(engaged_contents).lower() if engaged_contents else ""
        matched_existing = set()
        for kw in items:
            if kw in engaged_lower:
                matched_existing.add(kw)

        all_engaged = engaged_keywords | matched_existing

        # 1. BOOST + DECAY existing interests
        for kw, item in list(items.items()):
            if kw in all_engaged:
                # BOOST
                item.weight += traits.impressionability
                item.weight = min(1.0, item.weight)
                item.last_engaged = round_num
                item.engagement_count += 1
            else:
                # DECAY
                item.weight *= (1.0 - traits.forgetfulness)

            # FLOOR for profile interests
            if item.source == "profile":
                floor = traits.conviction * 0.3
                item.weight = max(floor, item.weight)

        # 2. NEW: add new keywords from engagement
        for kw in engaged_keywords:
            if kw not in items and len(items) < self.MAX_INTERESTS:
                items[kw] = InterestItem(
                    keyword=kw,
                    weight=traits.curiosity,
                    source="drift",
                    first_seen=round_num,
                    last_engaged=round_num,
                )
                items[kw].engagement_count = 1

        # 3. Graph entities as interests
        if graph_entities:
            for entity in graph_entities[:2]:
                ent_lower = entity.lower()
                if ent_lower not in items and len(items) < self.MAX_INTERESTS:
                    items[ent_lower] = InterestItem(
                        keyword=entity,
                        weight=traits.curiosity * 0.7,
                        source="graph",
                        first_seen=round_num,
                    )

        # 4. PRUNE: remove too-weak non-profile interests
        items_to_remove = [
            kw for kw, item in items.items()
            if item.weight < 0.03 and item.source != "profile"
        ]
        for kw in items_to_remove:
            del items[kw]

        # Save snapshot for history chart
        self._history[agent_id].append(
            {item.keyword: item.weight for item in
             sorted(items.values(), key=lambda x: -x.weight)}
        )

    def get_top_interests(self, agent_id: int, n: int = 5) -> List[tuple]:
        """Get top N interests sorted by weight.

        Returns list of (keyword, weight) tuples.
        """
        items = self._vectors.get(agent_id, {})
        sorted_items = sorted(items.values(), key=lambda x: -x.weight)
        return [(item.keyword, item.weight) for item in sorted_items[:n]]

    def get_search_queries(self, agent_id: int, n: int = 5) -> List[tuple]:
        """Get search queries with weights for multi-query ChromaDB search.

        Returns list of (query_text, weight) tuples.
        """
        return self.get_top_interests(agent_id, n)

    def get_drift_text(self, agent_id: int) -> str:
        """Backward-compatible: return top interest keywords as text."""
        top = self.get_top_interests(agent_id, 5)
        return " ".join(kw for kw, _ in top) if top else ""

    def get_drift_count(self, agent_id: int) -> int:
        """Backward-compatible: count of interests."""
        return len(self._vectors.get(agent_id, {}))

    def get_items(self, agent_id: int) -> List[dict]:
        """Get all interest items as dicts for tracking/display."""
        items = self._vectors.get(agent_id, {})
        return [item.to_dict() for item in
                sorted(items.values(), key=lambda x: -x.weight)]

    def get_traits(self, agent_id: int) -> Optional[CognitiveTraits]:
        """Get cognitive traits for an agent."""
        return self._traits.get(agent_id)

    def get_history(self, agent_id: int) -> list:
        """Get per-round interest weight snapshots for charting."""
        return self._history.get(agent_id, [])


# Backward compatibility alias
InterestTracker = InterestVectorTracker


# ══════════════════════════════════════════════════════════════
# Phase 4: Reflection (Persona Evolution)
# ══════════════════════════════════════════════════════════════

class AgentReflection:
    """Periodic persona evolution through LLM-generated insights.

    Every `interval` rounds, the agent's recent memory is fed to an
    LLM which synthesizes 1-2 insights about how the agent's views
    or interests have shifted. These insights are appended to the
    base persona to create an "evolved persona".

    The base persona is NEVER modified — insights are layered on top,
    ensuring the agent's core identity is preserved.

    Reference: Generative Agents (Stanford) — importance-triggered reflection.

    Requirements: Agent Memory (Phase 1) must be enabled.
    """

    MAX_INSIGHTS = 3  # Keep latest 3 insights per agent

    def __init__(self, interval: int = 3):
        """
        Args:
            interval: Reflect every N rounds. Default 3.
        """
        self.interval = max(1, interval)
        # agent_id → list of insight strings
        self._insights: Dict[int, list] = defaultdict(list)

    async def maybe_reflect(self, agent_id: int, round_num: int,
                            memory: 'AgentMemory', model,
                            base_persona: str,
                            graph_context: str = "") -> Optional[str]:
        """Conditionally trigger reflection for an agent.

        Only triggers if round_num is divisible by interval AND
        the agent has memory context to reflect on.

        Args:
            agent_id: Agent to reflect.
            round_num: Current round number.
            memory: AgentMemory instance (required).
            model: LLM model backend for generating insights.
            base_persona: Agent's original persona string.
            graph_context: Optional social context from knowledge graph.

        Returns:
            Generated insight string if reflection triggered, None otherwise.
        """
        if round_num % self.interval != 0:
            return None

        mem_ctx = memory.get_context(agent_id)
        if not mem_ctx:
            return None

        try:
            from camel.agents import ChatAgent
            from camel.messages import BaseMessage

            sys_msg = BaseMessage.make_assistant_message(
                role_name="Reflector",
                content=(
                    "You are analyzing a social media user's recent activity. "
                    "Based on their profile and actions, generate exactly ONE "
                    "brief insight (1 sentence) about how their views, interests, "
                    "or engagement patterns may have shifted. Be specific and "
                    "grounded in the evidence. Write in English."
                ),
            )
            agent = ChatAgent(system_message=sys_msg, model=model)

            # Build prompt with memory + optional graph context
            prompt_parts = [f"User profile: {base_persona[:300]}", mem_ctx]
            if graph_context:
                prompt_parts.append(
                    f"Social relationships from knowledge graph:\n{graph_context}"
                )
            prompt_parts.append(
                "What insight can you draw about how this user's "
                "perspective or interests may be evolving?"
            )

            user_msg = BaseMessage.make_user_message(
                role_name="User",
                content="\n\n".join(prompt_parts),
            )
            resp = await agent.astep(user_msg)
            insight = resp.msgs[0].content.strip() if resp.msgs else ""

            if insight and len(insight) > 10:
                # Cap stored insights
                self._insights[agent_id].append(insight)
                if len(self._insights[agent_id]) > self.MAX_INSIGHTS:
                    self._insights[agent_id] = \
                        self._insights[agent_id][-self.MAX_INSIGHTS:]
                return insight
        except Exception as e:
            print(f"   WARN: Reflection failed for agent {agent_id}: {e}")

        return None

    def get_evolved_persona(self, agent_id: int, base_persona: str) -> str:
        """Get persona with accumulated reflection insights.

        If no insights exist, returns base_persona unchanged.

        Args:
            agent_id: Agent ID.
            base_persona: Original static persona string.

        Returns:
            Base persona + appended insights section, or just base.
        """
        insights = self._insights.get(agent_id, [])
        if not insights:
            return base_persona
        insights_text = "; ".join(insights)
        return f"{base_persona}\n\nRecent reflections: {insights_text}"

    def get_insight_count(self, agent_id: int) -> int:
        """Get number of reflection insights stored for this agent."""
        return len(self._insights.get(agent_id, []))


# ══════════════════════════════════════════════════════════════
# Phase 5: Knowledge Graph Cognitive Integration
# ══════════════════════════════════════════════════════════════

class GraphCognitiveHelper:
    """Query FalkorDB knowledge graph to enrich cognitive context.

    Wraps FalkorGraphSearcher to provide two key capabilities:
    1. Social Context — who interacted with whom, what they discussed
    2. Interest Entities — key entities from the graph related to an agent

    This is the bridge between the graph memory (write-side) and
    the cognitive layer (read-side). Without this, cognitive modules
    only use simple in-memory structures.

    Toggle: enable_graph_cognition in SIM_CONFIG.
    Requires: FalkorDB running (Docker).
    """

    def __init__(self, falkor_host: str = "localhost",
                 falkor_port: int = 6379,
                 group_id: str = ""):
        self.falkor_host = falkor_host
        self.falkor_port = falkor_port
        self.group_id = group_id
        self._searcher = None
        self._connected = False

    async def _ensure_connected(self):
        """Lazy-init: connect to FalkorDB on first query."""
        if self._connected:
            return True
        try:
            from falkor_graph_memory import FalkorGraphSearcher
            self._searcher = FalkorGraphSearcher(
                falkor_host=self.falkor_host,
                falkor_port=self.falkor_port,
            )
            await self._searcher.connect()
            self._connected = True
            return True
        except Exception as e:
            print(f"[GRAPH-COG] FalkorDB connection failed: {e}")
            return False

    async def get_social_context(self, agent_name: str,
                                 num_results: int = 5) -> str:
        """Query graph for agent's social relationships and interactions.

        Returns a text summary of who the agent interacted with and
        what topics were discussed — used to enrich reflection and
        post/comment generation prompts.

        Args:
            agent_name: Agent's real name (e.g. "Ly Thi Khoi").
            num_results: Max graph results to retrieve.

        Returns:
            Human-readable social context string, or "" if unavailable.
        """
        if not await self._ensure_connected():
            return ""

        try:
            results = await self._searcher.search(
                query=f"What has {agent_name} done and who did they interact with?",
                group_id=self.group_id,
                num_results=num_results,
            )
            if not results:
                return ""

            # Format graph results into readable context
            lines = []
            for r in results:
                # Graphiti search returns objects with .fact or .content
                fact = getattr(r, 'fact', None) or getattr(r, 'content', None) or str(r)
                if fact and len(str(fact)) > 10:
                    lines.append(f"- {fact}")

            return "\n".join(lines[:num_results]) if lines else ""

        except Exception as e:
            print(f"[GRAPH-COG] Search failed for {agent_name}: {e}")
            return ""

    async def get_interest_entities(self, agent_name: str,
                                    num_results: int = 5) -> List[str]:
        """Query graph entity nodes related to this agent.

        Extracts key entity names from the knowledge graph that are
        connected to this agent's activity — used to enrich interest
        drift beyond simple keyword extraction.

        Args:
            agent_name: Agent's real name.
            num_results: Max entities to return.

        Returns:
            List of entity name strings, or [] if unavailable.
        """
        if not await self._ensure_connected():
            return []

        try:
            nodes = await self._searcher.get_nodes(
                query=agent_name,
                num_results=num_results,
            )
            if not nodes:
                return []

            entities = []
            for node in nodes:
                name = getattr(node, 'name', None) or str(node)
                if name and len(name) > 2 and name.lower() != agent_name.lower():
                    entities.append(name)

            return entities[:num_results]

        except Exception as e:
            print(f"[GRAPH-COG] Entity query failed for {agent_name}: {e}")
            return []

    async def close(self):
        """Close the underlying graph connection."""
        if self._searcher:
            try:
                await self._searcher.close()
            except Exception:
                pass
            self._connected = False


"""
Interest-Based Feed Recommendation + Personality-Driven Posting

Uses ChromaDB with all-MiniLM-L6-v2 (default sentence-transformer) for
semantic similarity matching between agent interests and post content.

Key design:
- Model runs locally, no API calls needed
- Pre-download model at setup time to avoid slow first-run
- Calibrated cosine distance thresholds for all-MiniLM-L6-v2
- Rule-based action decisions (replaces expensive LLMAction)
"""
import logging
import os
import random as _random
import sqlite3
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("ecosim.interest_feed")


def pre_download_model():
    """Pre-download the all-MiniLM-L6-v2 model used by ChromaDB.

    Call this during prepare_simulation so the model is cached
    before the simulation starts. Subsequent calls are instant.
    """
    try:
        import chromadb
        client = chromadb.Client()
        col = client.get_or_create_collection("_warmup")
        col.add(ids=["warmup"], documents=["warmup text"])
        col.query(query_texts=["test"], n_results=1)
        client.delete_collection("_warmup")
        logger.info("ChromaDB embedding model warmed up successfully")
    except Exception as e:
        logger.warning("Model pre-download failed: %s", e)


class PostIndexer:
    """Indexes posts into ChromaDB for semantic similarity search.

    Uses all-MiniLM-L6-v2 (ChromaDB default) — runs locally, no API needed.
    """

    def __init__(self, collection_name: str = "ecosim_posts"):
        import chromadb
        self._client = chromadb.Client()  # in-memory
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._indexed_ids: set = set()
        logger.info("PostIndexer initialized with all-MiniLM-L6-v2 (collection=%s)",
                     collection_name)

    def index_post(self, post_id: int, content: str, author_id: int = -1,
                   round_num: int = 0):
        """Index a single post into ChromaDB."""
        doc_id = f"post_{post_id}"
        if doc_id in self._indexed_ids:
            return
        if not content or len(content.strip()) < 5:
            return

        try:
            self._collection.add(
                ids=[doc_id],
                documents=[content],
                metadatas=[{
                    "post_id": post_id,
                    "author_id": author_id,
                    "round_num": round_num,
                }],
            )
            self._indexed_ids.add(doc_id)
        except Exception as e:
            logger.warning("Failed to index post %d: %s", post_id, e)

    def index_from_db(self, db_path: str, round_num: int = 0) -> int:
        """Index all posts from the OASIS SQLite database."""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT post_id, user_id, content FROM post")
            rows = cursor.fetchall()
            conn.close()

            indexed = 0
            for post_id, user_id, content in rows:
                if content and len(content.strip()) >= 5:
                    before = len(self._indexed_ids)
                    self.index_post(post_id, content, user_id, round_num)
                    if len(self._indexed_ids) > before:
                        indexed += 1
            if indexed:
                logger.info("Indexed %d new posts (total: %d)", indexed,
                            len(self._indexed_ids))
            return indexed
        except Exception as e:
            logger.warning("Failed to index posts from DB: %s", e)
            return 0

    def query_by_interests(
        self, interests_text: str, n_results: int = 5
    ) -> List[Tuple[int, float]]:
        """Query ChromaDB for posts matching interests.

        Returns list of (post_id, cosine_distance) tuples sorted by relevance.
        Distance range for all-MiniLM-L6-v2 + cosine:
            0.0 = identical, ~0.5 = strong match, ~1.0 = moderate, ~1.5 = unrelated
        """
        if self._collection.count() == 0:
            return []

        try:
            actual_n = min(n_results, self._collection.count())
            if actual_n <= 0:
                return []

            results = self._collection.query(
                query_texts=[interests_text],
                n_results=actual_n,
                include=["metadatas", "distances"],
            )

            pairs = []
            if results and results["metadatas"] and results["distances"]:
                for meta, dist in zip(
                    results["metadatas"][0], results["distances"][0]
                ):
                    pid = meta.get("post_id")
                    if pid is not None:
                        pairs.append((int(pid), float(dist)))
            return pairs
        except Exception as e:
            logger.warning("ChromaDB query failed: %s", e)
            return []

    def query_post_ids(self, interests_text: str, n_results: int = 5) -> List[int]:
        """Convenience: return just post_ids."""
        return [pid for pid, _ in self.query_by_interests(interests_text, n_results)]

    def multi_query_search(
        self, interest_queries: List[Tuple[str, float]], n_results: int = 10
    ) -> List[Tuple[int, float]]:
        """Search ChromaDB with multiple weighted queries, merge via RRF.

        Each interest keyword gets its own ChromaDB query. Results are
        merged using Weighted Reciprocal Rank Fusion — higher-weight
        interests contribute more to the final ranking.

        Args:
            interest_queries: List of (query_text, weight) tuples.
            n_results: Max posts to return.

        Returns:
            List of (post_id, rrf_score) sorted by score descending.
        """
        if not interest_queries or self._collection.count() == 0:
            return []

        all_scores: Dict[int, float] = {}
        k = 60  # RRF constant

        for query_text, weight in interest_queries:
            if not query_text or weight <= 0:
                continue
            results = self.query_by_interests(query_text, n_results=n_results * 2)
            for rank, (post_id, distance) in enumerate(results):
                rrf_score = weight / (k + rank)
                all_scores[post_id] = all_scores.get(post_id, 0) + rrf_score

        if not all_scores:
            return []

        sorted_posts = sorted(all_scores.items(), key=lambda x: -x[1])
        return sorted_posts[:n_results]

    def get_post_content(self, post_id: int) -> str:
        """Get content of a specific post from ChromaDB."""
        doc_id = f"post_{post_id}"
        try:
            result = self._collection.get(ids=[doc_id], include=["documents"])
            if result and result["documents"]:
                return result["documents"][0]
        except Exception:
            pass
        return ""

    def get_post_author(self, post_id: int) -> int:
        """Get the author_id of a specific post."""
        doc_id = f"post_{post_id}"
        try:
            result = self._collection.get(ids=[doc_id], include=["metadatas"])
            if result and result["metadatas"]:
                return result["metadatas"][0].get("author_id", -1)
        except Exception:
            pass
        return -1

    def query_unified(
        self,
        interests_text: str,
        profiles: List[dict],
        engagement_tracker: 'EngagementTracker',
        agent_id: int,
        n_results: int = 5,
    ) -> List[Tuple[int, float]]:
        """Unified query: semantic + popularity + comment decay in one step.

        1. Query ChromaDB with large N (3x feed_size or all posts)
        2. Re-rank each post:
           final_distance = semantic_distance
                          - popularity_bonus(author_followers)
                          + comment_decay(agent_comment_count)
        3. Sort by final_distance, return top n_results

        This ensures posts already commented on by this agent are pushed
        down the ranking, while popular authors' posts are promoted.
        """
        total = self._collection.count()
        if total == 0:
            return []

        # Step 1: Query with large N to get broad candidate pool
        raw_n = min(total, max(n_results * 3, 20))
        raw_results = self.query_by_interests(interests_text, n_results=raw_n)
        if not raw_results:
            return []

        # Build author_id -> follower_count map
        author_followers: Dict[int, int] = {}
        for i, p in enumerate(profiles):
            author_followers[i] = p.get("followers", 0)

        # Step 2: Unified re-ranking
        rescored = []
        for post_id, semantic_dist in raw_results:
            # Popularity bonus: popular authors get lower distance
            author_id = self.get_post_author(post_id)
            followers = author_followers.get(author_id, 0)
            pop_bonus = min(0.25, followers / 20000.0) if followers > 0 else 0.0

            # Comment decay: posts this agent already commented get higher distance
            decay = engagement_tracker.get_decay(agent_id, post_id)

            final_dist = max(0.0, semantic_dist - pop_bonus + decay)
            rescored.append((post_id, final_dist))

        # Step 3: Sort and select top-K
        rescored.sort(key=lambda x: x[1])
        return rescored[:n_results]

    @property
    def count(self) -> int:
        return self._collection.count()


class EngagementTracker:
    """Tracks per-agent comment counts to apply decay in ranking.

    Each comment on a post adds +DECAY_PER_COMMENT to that post's
    distance for this agent. This pushes already-commented posts
    down the feed, spreading comments across more posts.
    """

    DECAY_PER_COMMENT = 0.3  # +0.3 distance per previous comment

    def __init__(self):
        # agent_id -> { post_id: comment_count }
        self._comments: Dict[int, Dict[int, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    def record_comment(self, agent_id: int, post_id: int):
        """Record that agent commented on a post."""
        self._comments[agent_id][post_id] += 1

    def get_comment_count(self, agent_id: int, post_id: int) -> int:
        """Get how many times agent commented on this post."""
        return self._comments[agent_id].get(post_id, 0)

    def get_decay(self, agent_id: int, post_id: int) -> float:
        """Get distance penalty for this agent+post.

        Returns comment_count * DECAY_PER_COMMENT.
        Example: 2 previous comments -> +0.6 distance penalty.
        """
        return self.get_comment_count(agent_id, post_id) * self.DECAY_PER_COMMENT


# ── Feed Size / Post Probability ──

def get_feed_size(daily_hours: float, feed_mult: float = 1.0) -> int:
    """Determine how many posts an agent sees based on daily screen time.

    Args:
        daily_hours: Agent's daily screen time.
        feed_mult: MBTI feed size multiplier (P=1.2, J=0.9). Default 1.0.
    """
    if daily_hours <= 0.5:
        base = 3
    elif daily_hours <= 1.0:
        base = 5
    elif daily_hours <= 1.5:
        base = 7
    elif daily_hours <= 2.0:
        base = 10
    elif daily_hours <= 3.0:
        base = 15
    else:
        base = 20
    return max(1, int(base * feed_mult))


def get_post_probability(profile: dict) -> float:
    """Probability an agent posts in a given round (posts_per_week / 7)."""
    posts_per_week = profile.get("posts_per_week", 3)
    return min(1.0, posts_per_week / 7.0)


def should_post(profile: dict, rng: _random.Random = None,
                post_mult: float = 1.0) -> bool:
    """Decide if this agent should create a post this round.

    Args:
        profile: Agent profile dict.
        rng: Random number generator.
        post_mult: MBTI post probability multiplier (E=1.2, I=0.8). Default 1.0.
    """
    prob = min(1.0, get_post_probability(profile) * post_mult)
    r = (rng or _random).random()
    return r < prob


def build_interest_text(profile: dict, drift_text: str = "") -> str:
    """Build the interest/query text from a profile for ChromaDB search.

    Priority order for building the search query:
    1. interests (explicit keyword list from profile)
    2. general_domain + specific_domain (structured field)
    3. drift_text (engagement-based keywords from Phase 3)
    4. campaign_context (short campaign description)
    5. Fallback: first sentence of original_persona or bio

    Args:
        profile: Agent profile dict.
        drift_text: Engagement-based drift keywords (Phase 3). Default "".
    """
    parts = []

    # 1. Explicit interests (if available)
    interests = profile.get("interests", [])
    if isinstance(interests, str) and interests:
        interests = [s.strip() for s in interests.split(",") if s.strip()]
    if interests:
        parts.append(" ".join(interests))

    # 2. Domain keywords (concise)
    gen_domain = profile.get("general_domain", "")
    spec_domain = profile.get("specific_domain", "")
    if spec_domain:
        parts.append(spec_domain)
    if gen_domain and gen_domain != spec_domain:
        parts.append(gen_domain)

    # 3. Drift keywords from engagement tracking
    if drift_text:
        parts.append(drift_text)

    # 4. Campaign context (short description)
    campaign_ctx = profile.get("campaign_context", "")
    if campaign_ctx:
        parts.append(campaign_ctx[:150])

    # 5. Fallback: extract first 1-2 sentences from persona or bio (not full text)
    if not parts:
        persona = profile.get("original_persona", "") or profile.get("persona", "")
        if persona:
            # Take first 2 sentences max
            sentences = persona.split(". ")
            short_persona = ". ".join(sentences[:2])
            parts.append(short_persona[:200])
        else:
            bio = profile.get("bio", "")
            if bio:
                parts.append(bio[:200])

    return " ".join(parts) if parts else "general topics social media"


# ── Rule-Based Action Decisions ──
# Calibrated thresholds for all-MiniLM-L6-v2 cosine distance:
#   < 0.7  = strong match
#   0.7-1.0 = moderate match
#   1.0-1.3 = weak match
#   > 1.3  = no match

STRONG_THRESHOLD = 0.7
MODERATE_THRESHOLD = 1.0
WEAK_THRESHOLD = 1.3


def decide_agent_actions(
    profile: dict,
    post_indexer: PostIndexer,
    db_path: str,
    rng: _random.Random = None,
    all_profiles: List[dict] = None,
    engagement_tracker: Optional[EngagementTracker] = None,
    agent_id: int = -1,
    comment_mult: float = 1.0,
    like_mult: float = 1.0,
    feed_mult: float = 1.0,
    drift_text: str = "",
    interest_queries: List[tuple] = None,
) -> List[dict]:
    """Decide agent actions using unified ranking -- RULE-BASED, no LLM.

    Pipeline:
    1. query_unified() combines semantic + popularity + comment decay
    2. Thresholds on final_distance determine like/comment probability
    3. Comments are recorded for future decay

    Thresholds (on final_distance after re-ranking):
    - < 0.7  (strong match):   LIKE 100% + COMMENT 50%
    - 0.7-1.0 (moderate match): LIKE 75%  + COMMENT 15%
    - 1.0-1.3 (weak match):    LIKE 30%
    - > 1.3  (no match):       LIKE 10% (random scroll behavior)

    Args:
        comment_mult: MBTI comment probability multiplier (E=1.3, I=0.7).
        like_mult: MBTI like probability multiplier (F=1.2, T=0.9).
        feed_mult: MBTI feed size multiplier (P=1.2, J=0.9).
        interest_queries: List of (query, weight) for multi-query search.
    """
    rng = rng or _random.Random()

    interest_text = build_interest_text(profile, drift_text=drift_text)
    daily_hours = profile.get("daily_hours", 1.0)
    feed_size = get_feed_size(daily_hours, feed_mult=feed_mult)

    # Unified query: semantic + popularity + comment decay in one step
    if all_profiles and engagement_tracker and agent_id >= 0:
        matches = post_indexer.query_unified(
            interest_text, all_profiles, engagement_tracker,
            agent_id, n_results=feed_size,
        )
    elif all_profiles:
        # Fallback: just semantic + popularity (no decay tracker)
        matches = post_indexer.query_unified(
            interest_text, all_profiles, EngagementTracker(),
            agent_id, n_results=feed_size,
        )
    else:
        matches = post_indexer.query_by_interests(interest_text, n_results=feed_size)

    if not matches:
        return [{"type": "do_nothing"}]

    # Activity multiplier: casual=0.7, regular=0.85, active=1.0, power=1.15
    activity_mult = min(1.2, max(0.7, 0.5 + daily_hours * 0.25))

    actions = []
    for post_id, distance in matches:
        if distance < STRONG_THRESHOLD:
            like_prob = 1.0 * activity_mult * like_mult
            comment_prob = 0.50 * activity_mult * comment_mult
        elif distance < MODERATE_THRESHOLD:
            like_prob = 0.75 * activity_mult * like_mult
            comment_prob = 0.15 * activity_mult * comment_mult
        elif distance < WEAK_THRESHOLD:
            like_prob = 0.30 * activity_mult * like_mult
            comment_prob = 0.0
        else:
            like_prob = 0.10 * activity_mult * like_mult
            comment_prob = 0.0

        if rng.random() < like_prob:
            actions.append({"type": "like_post", "post_id": post_id})

        if comment_prob > 0 and rng.random() < comment_prob:
            actions.append({
                "type": "create_comment",
                "post_id": post_id,
                "needs_llm": True,
            })

    # Guarantee at least 1 interaction
    if not actions and matches:
        best_pid = matches[0][0]
        actions.append({"type": "like_post", "post_id": best_pid})

    if not actions:
        actions.append({"type": "do_nothing"})

    return actions


# ── Rec Table Update ──

def update_rec_table_with_interests(
    db_path: str,
    post_indexer: PostIndexer,
    profiles: List[dict],
    interest_drifts: dict = None,
    interest_vectors: object = None,
):
    """Update the OASIS rec table with personalized post recommendations.

    Args:
        interest_drifts: dict of agent_id → drift_text (Phase 3). Default None.
        interest_vectors: InterestVectorTracker instance (Phase 3 v2).
    """
    if post_indexer.count == 0:
        logger.info("No posts indexed yet, skipping rec table update")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rec")

    insert_values = []
    for agent_id, profile in enumerate(profiles):
        daily_hours = profile.get("daily_hours", 1.0)
        feed_size = get_feed_size(daily_hours)

        # Use multi-query search if interest vectors available
        if interest_vectors and hasattr(interest_vectors, 'get_search_queries'):
            queries = interest_vectors.get_search_queries(agent_id, n=5)
            if queries:
                results = post_indexer.multi_query_search(queries, n_results=feed_size)
                post_ids = [pid for pid, _ in results]
            else:
                post_ids = []
        else:
            # Fallback: single query
            drift = (interest_drifts or {}).get(agent_id, "")
            interest_text = build_interest_text(profile, drift_text=drift)
            post_ids = post_indexer.query_post_ids(interest_text, n_results=feed_size)

        if not post_ids:
            cursor.execute("SELECT post_id FROM post")
            all_posts = [row[0] for row in cursor.fetchall()]
            post_ids = all_posts[:feed_size] if all_posts else []

        for post_id in post_ids:
            insert_values.append((agent_id, post_id))

    if insert_values:
        cursor.executemany(
            "INSERT INTO rec (user_id, post_id) VALUES (?, ?)",
            insert_values,
        )
        conn.commit()
        logger.info("Updated rec table: %d recommendations for %d agents",
                     len(insert_values), len(profiles))
    conn.close()

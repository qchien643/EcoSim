"""
Graph Memory Updater — Real-time KG updates during simulation.

Pattern: MiroFish ZepGraphMemoryUpdater (background thread + batch writes)
Target: FalkorDB campaign Knowledge Graph (graph: "ecosim")

Data Flow:
    Simulation subprocess → actions.jsonl → Monitor thread → Queue → Worker → FalkorDB
    
New nodes/edges added to KG during simulation:
    (:SimAgent {name, agent_id, sim_id}) — simulation agent instance
    (:SimPost {content, round, sentiment})  — posts created during sim
    (:SimAgent)-[:SIM_POSTED]→(:SimPost)
    (:SimAgent)-[:SIM_LIKED]→(:SimPost)
    (:SimAgent)-[:SIM_FOLLOWED]→(:SimAgent)
    (:SimAgent)-[:SIM_COMMENTED {content}]→(:SimPost)
    (:SimAgent)-[:SIM_REPOSTED]→(:SimPost)
    (:SimAgent)-[:REPRESENTS]→(:Entity)    — link to campaign KG entity
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from queue import Empty, Queue
from typing import Any, Dict, List, Optional

from ..config import Config

logger = logging.getLogger("ecosim.graph_memory_updater")


class GraphMemoryUpdater:
    """Real-time FalkorDB updater for simulation actions.
    
    Monitors actions.jsonl and writes agent interactions to the campaign KG.
    Unlike AgentMemoryManager (which uses a separate memory graph),
    this writes directly to the main campaign graph ("ecosim").
    """

    BATCH_SIZE = 5
    FLUSH_INTERVAL = 10  # seconds
    MAX_RETRIES = 2

    def __init__(self, sim_id: str, agent_names: Optional[Dict[int, str]] = None):
        self.sim_id = sim_id
        self.agent_names = agent_names or {}
        self._graph = None
        self._queue: Queue = Queue()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Stats
        self._total_queued = 0
        self._total_sent = 0
        self._total_items_sent = 0
        self._failed_count = 0
        self._skipped_count = 0

    def _get_graph(self):
        """Lazy FalkorDB connection."""
        if self._graph is None:
            try:
                from falkordb import FalkorDB
                client = FalkorDB(
                    host=Config.FALKORDB_HOST,
                    port=Config.FALKORDB_PORT,
                )
                self._graph = client.select_graph("ecosim")
                logger.info(f"GraphMemoryUpdater connected to FalkorDB: ecosim")
            except Exception as e:
                logger.warning(f"FalkorDB unavailable: {e}")
                return None
        return self._graph

    def start(self):
        """Start background worker thread."""
        if self._running:
            return

        graph = self._get_graph()
        if graph is None:
            logger.warning("Cannot start GraphMemoryUpdater: FalkorDB unavailable")
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"GraphMemoryUpdater-{self.sim_id[:8]}",
        )
        self._worker_thread.start()
        logger.info(f"GraphMemoryUpdater started: sim_id={self.sim_id}")

    def stop(self, flush: bool = True):
        """Stop worker thread, optionally flushing remaining items."""
        self._running = False

        if flush:
            self._flush_remaining()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

        logger.info(
            f"GraphMemoryUpdater stopped: sim_id={self.sim_id}, "
            f"queued={self._total_queued}, sent={self._total_items_sent}, "
            f"failed={self._failed_count}, skipped={self._skipped_count}"
        )

    def add_action(self, action: Dict[str, Any]):
        """Add an action to the update queue.
        
        Args:
            action: Parsed action dict from actions.jsonl with keys:
                - action_type: CREATE_POST, LIKE_POST, FOLLOW, etc.
                - agent_id: int
                - agent_name: str (optional)
                - content: str (optional)
                - round: int (optional)
        """
        action_type = action.get("action_type", "").upper()

        # Skip DO_NOTHING
        if action_type == "DO_NOTHING" or not action_type:
            self._skipped_count += 1
            return

        self._queue.put(action)
        self._total_queued += 1

    def add_action_from_line(self, jsonl_line: str):
        """Parse a JSONL line and add to queue."""
        try:
            data = json.loads(jsonl_line.strip())
            if data:
                self.add_action(data)
        except (json.JSONDecodeError, Exception):
            pass

    # ── Worker Thread ──

    def _worker_loop(self):
        """Background loop: collect batch, convert to Cypher, write to FalkorDB."""
        buffer: List[Dict] = []
        last_flush = time.time()

        while self._running or not self._queue.empty():
            try:
                try:
                    action = self._queue.get(timeout=1)
                    buffer.append(action)
                except Empty:
                    pass

                # Flush when batch full or interval elapsed
                now = time.time()
                if len(buffer) >= self.BATCH_SIZE or (
                    buffer and (now - last_flush) >= self.FLUSH_INTERVAL
                ):
                    self._write_batch(buffer)
                    buffer = []
                    last_flush = now

            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                time.sleep(1)

    def _flush_remaining(self):
        """Flush everything in queue + buffer."""
        remaining = []
        while not self._queue.empty():
            try:
                remaining.append(self._queue.get_nowait())
            except Empty:
                break

        if remaining:
            self._write_batch(remaining)

    # ── Cypher Writing ──

    def _write_batch(self, actions: List[Dict]):
        """Write a batch of actions to FalkorDB as KG nodes/edges."""
        graph = self._get_graph()
        if not graph:
            self._failed_count += 1
            return

        for attempt in range(self.MAX_RETRIES):
            try:
                written = 0
                for action in actions:
                    if self._write_single_action(graph, action):
                        written += 1

                self._total_sent += 1
                self._total_items_sent += written
                logger.debug(
                    f"Batch written: {written}/{len(actions)} actions to KG"
                )
                return

            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"Batch write failed (attempt {attempt+1}): {e}")
                    time.sleep(2 * (attempt + 1))
                else:
                    logger.error(f"Batch write failed after {self.MAX_RETRIES} retries: {e}")
                    self._failed_count += 1

    def _write_single_action(self, graph, action: Dict) -> bool:
        """Convert a single action to Cypher and execute.
        
        Supports rich context fields: agent_name, post_content, post_author_name,
        target_user_name (from _get_round_actions_rich).
        
        Returns True if written successfully, False if skipped.
        """
        action_type = action.get("action_type", "").upper()
        agent_id = action.get("agent_id", -1)
        agent_name = action.get("agent_name", "") or self.agent_names.get(agent_id, f"Agent_{agent_id}")
        content = action.get("content", "")
        round_num = action.get("round", 0)
        timestamp = action.get("timestamp", datetime.now().isoformat())

        try:
            if action_type == "CREATE_POST" and content:
                # Create SimPost node + SIM_POSTED edge
                post_id = action.get("post_id", f"{self.sim_id}_{agent_id}_{round_num}_{hash(content) % 10000}")
                graph.query(
                    "MERGE (a:SimAgent {agent_id: $aid, sim_id: $sid}) "
                    "SET a.name = $name "
                    "MERGE (p:SimPost {post_id: $pid}) "
                    "SET p.content = $content, p.round = $round, p.created_at = $ts, "
                    "    p.sim_id = $sid, p.author_name = $name "
                    "MERGE (a)-[:SIM_POSTED {round: $round}]->(p)",
                    params={
                        "aid": agent_id, "sid": self.sim_id, "name": agent_name,
                        "pid": str(post_id), "content": content[:500], "round": round_num,
                        "ts": timestamp,
                    },
                )
                return True

            elif action_type == "CREATE_COMMENT" and content:
                post_id = action.get("post_id", f"{self.sim_id}_{agent_id}_{round_num}_cmt_{hash(content) % 10000}")
                post_content = action.get("post_content", "")[:200]
                post_author = action.get("post_author_name", "")
                graph.query(
                    "MERGE (a:SimAgent {agent_id: $aid, sim_id: $sid}) "
                    "SET a.name = $name "
                    "MERGE (p:SimPost {post_id: $pid}) "
                    "SET p.content = $content, p.round = $round, p.created_at = $ts, "
                    "    p.sim_id = $sid, p.is_comment = true, p.author_name = $name "
                    "MERGE (a)-[:SIM_COMMENTED {round: $round, "
                    "    post_content: $pcontent, post_author: $pauthor}]->(p)",
                    params={
                        "aid": agent_id, "sid": self.sim_id, "name": agent_name,
                        "pid": str(post_id), "content": content[:500], "round": round_num,
                        "ts": timestamp, "pcontent": post_content, "pauthor": post_author,
                    },
                )
                return True

            elif action_type == "LIKE_POST":
                target_id = action.get("post_id", action.get("target_post_id", 0))
                post_content = action.get("post_content", "")[:200]
                post_author = action.get("post_author_name", "")
                graph.query(
                    "MERGE (a:SimAgent {agent_id: $aid, sim_id: $sid}) "
                    "SET a.name = $name "
                    "MERGE (t:SimPost {post_id: $tid}) "
                    "SET t.content = CASE WHEN t.content IS NULL AND $pcontent <> '' "
                    "    THEN $pcontent ELSE t.content END, "
                    "    t.author_name = CASE WHEN t.author_name IS NULL AND $pauthor <> '' "
                    "    THEN $pauthor ELSE t.author_name END "
                    "MERGE (a)-[:SIM_LIKED {round: $round, post_author: $pauthor}]->(t)",
                    params={
                        "aid": agent_id, "sid": self.sim_id, "name": agent_name,
                        "tid": str(target_id), "round": round_num,
                        "pcontent": post_content, "pauthor": post_author,
                    },
                )
                return True

            elif action_type == "FOLLOW":
                target_id = action.get("followee_id", action.get("target_user_id", 0))
                target_name = action.get("target_user_name", "") or self.agent_names.get(target_id, f"Agent_{target_id}")
                graph.query(
                    "MERGE (a:SimAgent {agent_id: $aid, sim_id: $sid}) "
                    "SET a.name = $name "
                    "MERGE (b:SimAgent {agent_id: $tid, sim_id: $sid}) "
                    "SET b.name = $tname "
                    "MERGE (a)-[:SIM_FOLLOWED {round: $round}]->(b)",
                    params={
                        "aid": agent_id, "sid": self.sim_id, "name": agent_name,
                        "tid": target_id, "tname": target_name, "round": round_num,
                    },
                )
                return True

            elif action_type == "REPOST":
                target_id = action.get("post_id", action.get("target_post_id", 0))
                post_content = action.get("post_content", "")[:200]
                post_author = action.get("post_author_name", "")
                graph.query(
                    "MERGE (a:SimAgent {agent_id: $aid, sim_id: $sid}) "
                    "SET a.name = $name "
                    "MERGE (t:SimPost {post_id: $tid}) "
                    "SET t.content = CASE WHEN t.content IS NULL AND $pcontent <> '' "
                    "    THEN $pcontent ELSE t.content END, "
                    "    t.author_name = CASE WHEN t.author_name IS NULL AND $pauthor <> '' "
                    "    THEN $pauthor ELSE t.author_name END "
                    "MERGE (a)-[:SIM_REPOSTED {round: $round, post_author: $pauthor}]->(t)",
                    params={
                        "aid": agent_id, "sid": self.sim_id, "name": agent_name,
                        "tid": str(target_id), "round": round_num,
                        "pcontent": post_content, "pauthor": post_author,
                    },
                )
                return True

            else:
                return False

        except Exception as e:
            logger.debug(f"Write action failed ({action_type}): {e}")
            return False

    # ── Agent Seeding via Graphiti ──

    async def seed_agents_via_graphiti(self, profiles: List[Dict], kg_edges: List[Dict] = None):
        """Seed agent profiles into KG using Graphiti add_episode().

        Graphiti auto-extracts entities and relationships from the text,
        making them searchable via hybrid search (BM25 + Vector + RRF).

        Also creates raw SimAgent nodes for direct Cypher queries.
        """
        from .graphiti_service import get_graphiti_client

        # Phase 1: Raw Cypher — create SimAgent nodes (fast, for direct queries)
        graph = self._get_graph()
        if graph:
            for prof in profiles:
                aid = prof.get("agent_id", 0)
                name = prof.get("name", f"Agent_{aid}")
                entity_type = prof.get("entity_type", prof.get("role", ""))
                topics = prof.get("topics", [])
                if isinstance(topics, str):
                    try:
                        topics = json.loads(topics)
                    except (json.JSONDecodeError, ValueError):
                        topics = []

                try:
                    graph.query(
                        "MERGE (a:SimAgent {agent_id: $aid, sim_id: $sid}) "
                        "SET a.name = $name, a.role = $role, "
                        "    a.entity_type = $etype, "
                        "    a.bio = $bio, a.topics = $topics, "
                        "    a.persona_summary = $persona",
                        params={
                            "aid": aid, "sid": self.sim_id,
                            "name": name, "role": entity_type,
                            "etype": entity_type,
                            "bio": (prof.get("bio", "") or "")[:200],
                            "topics": json.dumps(topics) if isinstance(topics, list) else str(topics),
                            "persona": (prof.get("persona", prof.get("user_char", "")) or "")[:300],
                        },
                    )
                except Exception as e:
                    logger.debug(f"Seed SimAgent node failed for {name}: {e}")

            # Link SimAgent → campaign Entity by name
            for prof in profiles:
                name = prof.get("name", "")
                if not name:
                    continue
                aid = prof.get("agent_id", 0)
                try:
                    graph.query(
                        "MATCH (a:SimAgent {agent_id: $aid, sim_id: $sid}) "
                        "MATCH (e:Entity {name: $name}) "
                        "MERGE (a)-[:REPRESENTS]->(e)",
                        params={"aid": aid, "sid": self.sim_id, "name": name},
                    )
                except Exception:
                    pass

            # KNOWS edges from KG relationships
            if kg_edges:
                name_to_id = {p.get("name", ""): p.get("agent_id") for p in profiles}
                for edge in kg_edges:
                    src_name = edge.get("source", "")
                    tgt_name = edge.get("target", "")
                    src_id = name_to_id.get(src_name)
                    tgt_id = name_to_id.get(tgt_name)
                    if src_id is not None and tgt_id is not None:
                        try:
                            graph.query(
                                "MATCH (a:SimAgent {agent_id: $src, sim_id: $sid}) "
                                "MATCH (b:SimAgent {agent_id: $tgt, sim_id: $sid}) "
                                "MERGE (a)-[:KNOWS {rel_type: $rel}]->(b)",
                                params={
                                    "src": src_id, "tgt": tgt_id,
                                    "sid": self.sim_id,
                                    "rel": edge.get("rel_type", "RELATED_TO"),
                                },
                            )
                        except Exception:
                            pass

            logger.info(f"Seeded {len(profiles)} SimAgent nodes via Cypher")

        # Phase 2: Graphiti episodes — for hybrid search
        client = await get_graphiti_client()
        if client:
            try:
                from graphiti_core.nodes import EpisodeType
                from datetime import datetime, timezone

                for prof in profiles:
                    name = prof.get("name", "")
                    role = prof.get("entity_type", prof.get("role", ""))
                    bio = prof.get("bio", "")
                    persona = (prof.get("persona", prof.get("user_char", "")) or "")[:500]
                    topics = prof.get("topics", [])
                    if isinstance(topics, str):
                        try:
                            topics = json.loads(topics)
                        except (json.JSONDecodeError, ValueError):
                            topics = []

                    episode_text = (
                        f"{name} is a {role}. {bio} "
                        f"Interests: {', '.join(topics) if isinstance(topics, list) else str(topics)}. "
                        f"{persona}"
                    )

                    await client.add_episode(
                        name=f"Agent: {name}",
                        episode_body=episode_text,
                        source_description="EcoSim agent profile",
                        source=EpisodeType.text,
                        reference_time=datetime.now(timezone.utc),
                        group_id=self.sim_id,
                    )

                # Seed KG edges as episodes too
                if kg_edges:
                    edge_lines = []
                    for e in kg_edges[:50]:
                        edge_lines.append(
                            f"{e.get('source', '')} {e.get('rel_type', 'relates to')} {e.get('target', '')}"
                        )
                    if edge_lines:
                        await client.add_episode(
                            name="Campaign Relationships",
                            episode_body="\n".join(edge_lines),
                            source_description="Campaign KG relationships",
                            source=EpisodeType.text,
                            reference_time=datetime.now(timezone.utc),
                            group_id=self.sim_id,
                        )

                logger.info(f"Seeded {len(profiles)} agent profiles via Graphiti episodes")
            except Exception as e:
                logger.warning(f"Graphiti episode seeding failed (non-fatal): {e}")
        else:
            logger.info("Graphiti not available, skipped episode seeding (raw Cypher done)")

    # ── Stats ──

    def get_stats(self) -> Dict[str, Any]:
        return {
            "sim_id": self.sim_id,
            "running": self._running,
            "total_queued": self._total_queued,
            "total_sent": self._total_items_sent,
            "batches_sent": self._total_sent,
            "failed_count": self._failed_count,
            "skipped_count": self._skipped_count,
            "queue_size": self._queue.qsize(),
        }


class GraphMemoryManager:
    """Static registry: manages one GraphMemoryUpdater per simulation."""

    _updaters: Dict[str, GraphMemoryUpdater] = {}
    _lock = threading.Lock()

    @classmethod
    def create_updater(
        cls,
        sim_id: str,
        agent_names: Optional[Dict[int, str]] = None,
    ) -> GraphMemoryUpdater:
        """Create and start an updater for a simulation."""
        with cls._lock:
            if sim_id in cls._updaters:
                cls._updaters[sim_id].stop(flush=False)

            updater = GraphMemoryUpdater(sim_id, agent_names)
            updater.start()
            cls._updaters[sim_id] = updater
            logger.info(f"GraphMemoryManager: created updater for {sim_id}")
            return updater

    @classmethod
    def get_updater(cls, sim_id: str) -> Optional[GraphMemoryUpdater]:
        return cls._updaters.get(sim_id)

    @classmethod
    def add_action(cls, sim_id: str, action: Dict):
        """Add action to the sim's updater (if exists)."""
        updater = cls._updaters.get(sim_id)
        if updater:
            updater.add_action(action)

    @classmethod
    def stop_updater(cls, sim_id: str, flush: bool = True):
        with cls._lock:
            if sim_id in cls._updaters:
                cls._updaters[sim_id].stop(flush=flush)
                del cls._updaters[sim_id]
                logger.info(f"GraphMemoryManager: stopped updater for {sim_id}")

    @classmethod
    def stop_all(cls):
        with cls._lock:
            for sim_id, updater in list(cls._updaters.items()):
                try:
                    updater.stop(flush=True)
                except Exception as e:
                    logger.error(f"Stop updater failed: {sim_id}: {e}")
            cls._updaters.clear()
            logger.info("GraphMemoryManager: stopped all updaters")

    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict]:
        return {
            sim_id: updater.get_stats()
            for sim_id, updater in cls._updaters.items()
        }

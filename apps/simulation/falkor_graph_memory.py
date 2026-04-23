"""
FalkorDB Graph Memory Updater
Ghi lại tương tác agent từ OASIS simulation vào FalkorDB knowledge graph
thông qua graphiti-core SDK.

Pattern: Tương tự MiroFish ZepGraphMemoryUpdater nhưng dùng FalkorDB self-hosted.
"""
import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Dict, List, Optional

logger = logging.getLogger("ecosim.graph_memory")


class FalkorGraphMemoryUpdater:
    """Background worker ghi simulation actions vào FalkorDB qua Graphiti.

    Architecture:
        Simulation loop → add_action(action) → Queue → Worker thread
        → batch 5 actions → action_to_text() → graphiti.add_episode()
        → FalkorDB auto-extracts entities & relationships
    """

    def __init__(
        self,
        simulation_id: str,
        falkor_host: str = "localhost",
        falkor_port: int = 6379,
        batch_size: int = 5,
        flush_interval: float = 10.0,
        agent_names: Optional[Dict[int, str]] = None,
    ):
        self.simulation_id = simulation_id
        self.falkor_host = falkor_host
        self.falkor_port = falkor_port
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.agent_names = agent_names or {}

        self._queue: Queue = Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._graphiti = None
        self._total_episodes = 0
        self._total_skipped = 0

    def start(self):
        """Launch background worker thread."""
        if self._running:
            logger.warning("Updater already running for sim %s", self.simulation_id)
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name=f"falkor-graph-{self.simulation_id}",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info(
            "🟢 FalkorDB graph memory started for sim=%s host=%s:%s",
            self.simulation_id, self.falkor_host, self.falkor_port,
        )

    def add_action(self, action: Dict):
        """Enqueue an action from the simulation loop (thread-safe)."""
        self._queue.put(action)

    def stop(self, flush: bool = True):
        """Stop worker thread, optionally flushing remaining queue items."""
        remaining = self._queue.qsize()
        logger.info(
            "Stopping graph memory (flush=%s, queue_size=%d, written=%d)...",
            flush, remaining, self._total_episodes,
        )
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            # Each episode takes ~5-10s for LLM extraction, give enough time
            timeout = max(300, remaining * 15)
            self._worker_thread.join(timeout=timeout)
        logger.info(
            "🔴 FalkorDB graph memory stopped for sim=%s | "
            "episodes=%d skipped=%d",
            self.simulation_id, self._total_episodes, self._total_skipped,
        )

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------
    def _worker_loop(self):
        """Main loop: collect batches → convert to text → send to Graphiti."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Initialize Graphiti connection
            loop.run_until_complete(self._init_graphiti())

            while self._running or not self._queue.empty():
                batch = self._collect_batch()
                if batch:
                    texts = []
                    for action in batch:
                        text = self._action_to_text(action)
                        if text:
                            texts.append((text, action))
                        else:
                            self._total_skipped += 1

                    if texts:
                        loop.run_until_complete(self._send_batch(texts))

            # Final flush
            remaining = []
            while not self._queue.empty():
                try:
                    remaining.append(self._queue.get_nowait())
                except Empty:
                    break
            if remaining:
                texts = [
                    (t, a) for a in remaining
                    if (t := self._action_to_text(a)) is not None
                ]
                if texts:
                    loop.run_until_complete(self._send_batch(texts))

            # Close connection
            loop.run_until_complete(self._close_graphiti())
        except Exception as e:
            logger.error("Graph memory worker crashed: %s", e, exc_info=True)
        finally:
            loop.close()

    def _collect_batch(self) -> List[Dict]:
        """Collect up to batch_size actions, or flush after interval."""
        batch = []
        deadline = time.time() + self.flush_interval

        while len(batch) < self.batch_size and time.time() < deadline:
            try:
                action = self._queue.get(timeout=1.0)
                batch.append(action)
            except Empty:
                if not self._running:
                    break
                continue
        return batch

    # ------------------------------------------------------------------
    # Graphiti integration
    # ------------------------------------------------------------------
    async def _init_graphiti(self):
        """Initialize Graphiti connection to FalkorDB."""
        from graphiti_core import Graphiti
        from graphiti_core.driver.falkordb_driver import FalkorDriver

        logger.info("Connecting to FalkorDB at %s:%s...", self.falkor_host, self.falkor_port)
        driver = FalkorDriver(host=self.falkor_host, port=self.falkor_port)
        self._graphiti = Graphiti(graph_driver=driver)
        await self._graphiti.build_indices_and_constraints()
        logger.info("✅ FalkorDB Graphiti connection established")

    async def _close_graphiti(self):
        """Close Graphiti connection."""
        if self._graphiti:
            await self._graphiti.close()
            logger.info("FalkorDB connection closed")

    async def _send_batch(self, texts: List[tuple]):
        """Send a batch of (text, action) pairs to Graphiti as episodes."""
        from graphiti_core.nodes import EpisodeType

        for i, (text, action) in enumerate(texts):
            try:
                ref_time = datetime.now(timezone.utc)
                if "timestamp" in action:
                    try:
                        ref_time = datetime.fromisoformat(action["timestamp"])
                    except (ValueError, TypeError):
                        pass

                round_num = action.get("round_num", 0)
                action_type = action.get("action_type", "unknown")

                await self._graphiti.add_episode(
                    name=f"sim_{self.simulation_id}_r{round_num}_{action_type}_{self._total_episodes}",
                    episode_body=text,
                    source=EpisodeType.text,
                    reference_time=ref_time,
                    source_description=f"OASIS Reddit simulation {self.simulation_id}",
                    group_id=self.simulation_id,
                )
                self._total_episodes += 1

            except Exception as e:
                logger.error(
                    "Failed to add episode (retry 1): %s | text=%s",
                    e, text[:100],
                )
                # Retry once
                try:
                    await asyncio.sleep(2)
                    await self._graphiti.add_episode(
                        name=f"sim_{self.simulation_id}_retry_{self._total_episodes}",
                        episode_body=text,
                        source=EpisodeType.text,
                        reference_time=datetime.now(timezone.utc),
                        source_description=f"OASIS Reddit simulation {self.simulation_id}",
                        group_id=self.simulation_id,
                    )
                    self._total_episodes += 1
                except Exception as e2:
                    logger.error("Retry failed: %s", e2)
                    self._total_skipped += 1

        logger.info(
            "📝 Batch sent: %d episodes (total: %d, skipped: %d)",
            len(texts), self._total_episodes, self._total_skipped,
        )

    # ------------------------------------------------------------------
    # Action → Natural language
    # ------------------------------------------------------------------
    def _get_agent_name(self, agent_id) -> str:
        """Resolve agent_id to human-readable name."""
        return self.agent_names.get(int(agent_id), f"Agent#{agent_id}")

    def _action_to_text(self, action: Dict) -> Optional[str]:
        """Convert structured action to natural language episode text.

        Returns None for actions that should be skipped (refresh, do_nothing).
        """
        action_type = action.get("action_type", "").lower()
        agent_id = action.get("user_id", action.get("agent_id", "?"))
        agent_name = self._get_agent_name(agent_id)
        info = action.get("info", {})

        # Parse info if it's a string
        if isinstance(info, str):
            try:
                import json
                info = json.loads(info)
            except (ValueError, TypeError):
                info = {"raw": info}

        # --- Post actions ---
        if action_type == "create_post":
            content = info.get("content", "")[:500]
            return f"Agent {agent_name} posted on Reddit: '{content}'"

        elif action_type == "like_post":
            post_author = info.get("post_author_name", "")
            post_content = info.get("post_content", "")
            if post_author and post_content:
                preview = post_content[:200].replace("\n", " ")
                return (
                    f"Agent {agent_name} liked a post by {post_author}: "
                    f"'{preview}'"
                )
            else:
                post_id = info.get("post_id", "?")
                return f"Agent {agent_name} liked post #{post_id}"

        elif action_type == "dislike_post":
            post_author = info.get("post_author_name", "")
            post_content = info.get("post_content", "")
            if post_author and post_content:
                preview = post_content[:200].replace("\n", " ")
                return (
                    f"Agent {agent_name} disliked a post by {post_author}: "
                    f"'{preview}'"
                )
            else:
                post_id = info.get("post_id", "?")
                return f"Agent {agent_name} disliked post #{post_id}"

        # --- Comment actions ---
        elif action_type == "create_comment":
            content = info.get("content", "")[:500]
            post_author = info.get("post_author_name", "")
            post_content = info.get("post_content", "")
            if post_author and post_content:
                post_preview = post_content[:150].replace("\n", " ")
                return (
                    f"Agent {agent_name} commented '{content}' on a post "
                    f"by {post_author} about '{post_preview}'"
                )
            else:
                post_id = info.get("post_id", "?")
                return (
                    f"Agent {agent_name} commented on post #{post_id}: "
                    f"'{content}'"
                )

        elif action_type == "like_comment":
            comment_id = info.get("comment_id", "?")
            return f"Agent {agent_name} liked comment #{comment_id}"

        elif action_type == "dislike_comment":
            comment_id = info.get("comment_id", "?")
            return f"Agent {agent_name} disliked comment #{comment_id}"

        # --- Social actions ---
        elif action_type == "follow":
            target_id = info.get("user_id", "?")
            target_name = self._get_agent_name(target_id)
            return f"Agent {agent_name} followed {target_name}"

        elif action_type == "mute":
            target_id = info.get("user_id", "?")
            target_name = self._get_agent_name(target_id)
            return f"Agent {agent_name} muted {target_name}"

        # --- Skip non-events ---
        elif action_type in ("refresh", "do_nothing", "sign_up", "trend",
                             "search_posts", "search_user"):
            return None

        else:
            logger.debug("Unknown action type: %s", action_type)
            return f"Agent {agent_name} performed {action_type}"


class FalkorGraphSearcher:
    """Query the FalkorDB knowledge graph after simulation.

    Provides search/retrieve capabilities for post-simulation analysis.
    """

    def __init__(self, falkor_host: str = "localhost", falkor_port: int = 6379,
                 database: str = "default_db"):
        self.falkor_host = falkor_host
        self.falkor_port = falkor_port
        self.database = database
        self._graphiti = None

    async def connect(self):
        from graphiti_core import Graphiti
        from graphiti_core.driver.falkordb_driver import FalkorDriver
        driver = FalkorDriver(
            host=self.falkor_host, port=self.falkor_port,
            database=self.database
        )
        self._graphiti = Graphiti(graph_driver=driver)

    async def close(self):
        if self._graphiti:
            await self._graphiti.close()

    async def search(self, query: str, group_id: str = None, num_results: int = 10,
                     search_method=None):
        """Semantic search over the knowledge graph using cross-encoder reranking."""
        from graphiti_core.search.search_config_recipes import SearchMethod
        if search_method is None:
            search_method = SearchMethod.COMBINED_HYBRID_SEARCH_RRF
        results = await self._graphiti.search(
            query=query,
            num_results=num_results,
            group_ids=[group_id] if group_id else None,
            search_method=search_method,
        )
        return results

    async def get_nodes(self, query: str, num_results: int = 10):
        """Find specific entities in the graph."""
        return await self._graphiti.retrieve_nodes(
            query=query,
            num_results=num_results,
        )

    async def get_episodes(self, query: str, num_results: int = 10):
        """Find specific episodes/events."""
        return await self._graphiti.retrieve_episodes(
            query=query,
            num_results=num_results,
        )

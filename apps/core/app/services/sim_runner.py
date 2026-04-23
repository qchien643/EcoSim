"""
Simulation Runner — Manages the simulation subprocess.

E2E Flow: API→SR→subprocess(run_simulation.py)→actions.jsonl
Launches simulation as a subprocess, streams progress, handles crisis injection.
Real-time KG update: monitors actions.jsonl → GraphMemoryUpdater → FalkorDB.
SSE streaming: broadcasts round events to subscribed clients.
"""

import csv
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

from ..config import Config
from ..models.simulation import SimStatus
from ..services.sim_manager import SimManager

logger = logging.getLogger("ecosim.sim_runner")


class SimRunner:
    """Run OASIS-style simulation as subprocess with SSE streaming."""

    # Class-level shared state (SimRunner is instantiated per-request)
    _processes: Dict[str, subprocess.Popen] = {}
    _event_queues: Dict[str, List[queue.Queue]] = {}  # sim_id → [Queue, ...]
    _event_lock = threading.Lock()

    def __init__(self):
        self.sim_manager = SimManager()

    # ── SSE Event Broadcasting ──

    @classmethod
    def subscribe(cls, sim_id: str) -> queue.Queue:
        """Subscribe to SSE events for a simulation. Returns a Queue."""
        q = queue.Queue(maxsize=100)
        with cls._event_lock:
            cls._event_queues.setdefault(sim_id, []).append(q)
        logger.info(f"SSE client subscribed to {sim_id} (total: {len(cls._event_queues.get(sim_id, []))})")
        return q

    @classmethod
    def unsubscribe(cls, sim_id: str, q: queue.Queue):
        """Unsubscribe a Queue from SSE events."""
        with cls._event_lock:
            queues = cls._event_queues.get(sim_id, [])
            if q in queues:
                queues.remove(q)
            if not queues:
                cls._event_queues.pop(sim_id, None)
        logger.info(f"SSE client unsubscribed from {sim_id}")

    @classmethod
    def _broadcast(cls, sim_id: str, event: dict):
        """Broadcast an event to all subscribed SSE clients."""
        with cls._event_lock:
            queues = cls._event_queues.get(sim_id, [])
            dead = []
            for q in queues:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                queues.remove(q)

    def start(self, sim_id: str, scenario_index: int = 0) -> Dict:
        """Start a simulation run.

        Args:
            sim_id: Simulation ID (must be in READY state)
            scenario_index: Which crisis scenario to use (0 = first crisis)
        """
        state = self.sim_manager.get(sim_id)
        if not state:
            return {"error": f"Simulation {sim_id} not found"}

        if state.status != SimStatus.READY:
            return {"error": f"Simulation must be in READY state, current: {state.status.value}"}

        # Build the subprocess command
        script_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts", "run_simulation.py"
        )
        script_path = os.path.abspath(script_path)

        cmd = [
            sys.executable, script_path,
            "--sim-id", sim_id,
            "--profiles", state.profiles_path,
            "--config", state.config_path,
            "--crisis", state.crisis_path,
            "--scenario-index", str(scenario_index),
            "--output-dir", state.output_dir,
        ]

        logger.info(f"Starting simulation: {' '.join(cmd)}")

        # Update status
        self.sim_manager.update_status(sim_id, SimStatus.RUNNING)

        # ── Start real-time KG updater + Seed agents ──
        agent_names = self._load_agent_names(state.profiles_path)
        try:
            from .graph_memory_updater import GraphMemoryManager
            updater = GraphMemoryManager.create_updater(sim_id, agent_names)
            logger.info(f"GraphMemoryUpdater started for {sim_id} ({len(agent_names)} agents)")

            # Seed agents into KG before simulation starts
            if updater:
                profiles_data, kg_edges = self._load_profiles_and_edges(state)
                if profiles_data:
                    import asyncio
                    try:
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(
                            updater.seed_agents_via_graphiti(profiles_data, kg_edges)
                        )
                        loop.close()
                        logger.info(f"Seeded {len(profiles_data)} agents into KG")
                    except Exception as e:
                        logger.warning(f"Agent seeding failed (non-fatal): {e}")
        except Exception as e:
            logger.warning(f"GraphMemoryUpdater not available: {e}")

        # Launch subprocess
        try:
            # Set UTF-8 encoding to prevent Windows cp1252 crashes from emoji
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=os.path.dirname(script_path),
            )
            self._processes[sim_id] = process

            # Monitor in background thread
            thread = threading.Thread(
                target=self._monitor,
                args=(sim_id, process),
                daemon=True,
            )
            thread.start()

            return {
                "sim_id": sim_id,
                "status": "running",
                "pid": process.pid,
                "output_dir": state.output_dir,
            }

        except Exception as e:
            logger.error(f"Failed to start simulation: {e}")
            self.sim_manager.update_status(sim_id, SimStatus.FAILED, str(e))
            # Stop KG updater on failure
            try:
                from .graph_memory_updater import GraphMemoryManager
                GraphMemoryManager.stop_updater(sim_id, flush=False)
            except Exception:
                pass
            return {"error": str(e)}

    def _load_agent_names(self, profiles_path: str) -> Dict[int, str]:
        """Load agent names from profiles CSV for KG node labels."""
        names = {}
        try:
            if profiles_path and os.path.exists(profiles_path):
                with open(profiles_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader):
                        names[idx] = row.get("name", row.get("username", f"Agent_{idx}"))
        except Exception as e:
            logger.debug(f"Could not load agent names: {e}")
        return names

    def _load_profiles_and_edges(self, state) -> tuple:
        """Load profile data and KG edges for agent seeding."""
        profiles_data = []

        # Prefer JSON (has topics, persona as proper types)
        json_path = state.profiles_path.replace(".csv", ".json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    profiles_data = json.load(f)
            except Exception as e:
                logger.debug(f"Could not load profiles JSON: {e}")

        # Fallback: CSV
        if not profiles_data and state.profiles_path and os.path.exists(state.profiles_path):
            try:
                with open(state.profiles_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader):
                        row["agent_id"] = idx
                        profiles_data.append(dict(row))
            except Exception as e:
                logger.debug(f"Could not load profiles CSV: {e}")

        # Load KG edges
        kg_edges = []
        try:
            from .graph_query import GraphQuery
            gq = GraphQuery()
            kg_edges = gq.get_all_edges(limit=100)
        except Exception as e:
            logger.debug(f"Could not load KG edges: {e}")

        logger.info(f"Loaded {len(profiles_data)} profiles, {len(kg_edges)} KG edges for seeding")
        return profiles_data, kg_edges

    def _monitor(self, sim_id: str, process: subprocess.Popen):
        """Monitor subprocess output, update state, and tail actions.jsonl for realtime KG updates."""
        state = self.sim_manager.get(sim_id)
        log_path = os.path.join(state.output_dir, "simulation.log")
        actions_path = os.path.join(state.output_dir, "actions.jsonl")

        # Import KG updater
        kg_updater = None
        try:
            from .graph_memory_updater import GraphMemoryManager
            kg_updater = GraphMemoryManager.get_updater(sim_id)
        except Exception:
            pass

        # File position tracker for realtime tailing
        actions_position = 0

        def _tail_actions():
            """Read new lines from actions.jsonl and feed to KG updater. Returns new actions."""
            nonlocal actions_position
            if not os.path.exists(actions_path):
                return []
            new_actions = []
            try:
                with open(actions_path, "r", encoding="utf-8") as f:
                    f.seek(actions_position)
                    for line in f:
                        if line.strip():
                            try:
                                action = json.loads(line)
                                new_actions.append(action)
                                if kg_updater:
                                    kg_updater.add_action_from_line(line)
                            except json.JSONDecodeError:
                                pass
                    actions_position = f.tell()
                if new_actions:
                    logger.info(f"[{sim_id}] Tailed {len(new_actions)} new actions (pos={actions_position})")
            except Exception as e:
                logger.debug(f"[{sim_id}] Tail actions error: {e}")
            return new_actions

        current_round = 0

        try:
            with open(log_path, "w", encoding="utf-8") as log_file:
                for line in process.stdout:
                    line = line.strip()
                    log_file.write(line + "\n")
                    log_file.flush()

                    # Parse progress updates
                    if line.startswith("ROUND:"):
                        try:
                            current_round = int(line.split(":")[1])
                            state = self.sim_manager.get(sim_id)
                            if state:
                                state.current_round = current_round
                                total = state.total_rounds or 1
                                # Broadcast round start event
                                SimRunner._broadcast(sim_id, {
                                    "event": "round_start",
                                    "round": current_round,
                                    "total_rounds": total,
                                    "progress_pct": round(current_round / total * 100, 1),
                                })
                        except (ValueError, IndexError):
                            pass

                    # Tail actions.jsonl after [ACTIONS] or [OK] lines (per-round flush)
                    if "[ACTIONS]" in line or "[OK]" in line:
                        new_actions = _tail_actions()
                        # Broadcast round completion signal (frontend fetches enriched actions)
                        state = self.sim_manager.get(sim_id)
                        total = state.total_rounds if state else 1
                        SimRunner._broadcast(sim_id, {
                            "event": "round_actions",
                            "round": current_round,
                            "total_rounds": total or 1,
                            "progress_pct": round(current_round / (total or 1) * 100, 1),
                            "action_count": len(new_actions) if new_actions else 0,
                        })

                    # Broadcast crisis injection events
                    if "[CRISIS]" in line:
                        SimRunner._broadcast(sim_id, {
                            "event": "crisis",
                            "round": current_round,
                            "message": line,
                        })

                    logger.debug(f"[{sim_id}] {line}")

            process.wait()
            exit_code = process.returncode

            # ── Final tail after subprocess ends ──
            _tail_actions()

            # ── Stop KG updater (flush remaining) ──
            try:
                from .graph_memory_updater import GraphMemoryManager
                GraphMemoryManager.stop_updater(sim_id, flush=True)
            except Exception:
                pass

            final_status = "completed" if exit_code == 0 else "failed"
            if exit_code == 0:
                self.sim_manager.update_status(sim_id, SimStatus.COMPLETED)
                logger.info(f"Simulation {sim_id} completed successfully")
            else:
                self.sim_manager.update_status(
                    sim_id, SimStatus.FAILED, f"Exit code: {exit_code}"
                )
                logger.error(f"Simulation {sim_id} failed with exit code {exit_code}")

            # Broadcast completion
            SimRunner._broadcast(sim_id, {
                "event": "done",
                "status": final_status,
                "round": current_round,
            })

        except Exception as e:
            self.sim_manager.update_status(sim_id, SimStatus.FAILED, str(e))
            logger.error(f"Monitor error: {e}")
            SimRunner._broadcast(sim_id, {
                "event": "done",
                "status": "failed",
                "error": str(e),
            })
            # Stop KG updater on error
            try:
                from .graph_memory_updater import GraphMemoryManager
                GraphMemoryManager.stop_updater(sim_id, flush=False)
            except Exception:
                pass

        finally:
            self._processes.pop(sim_id, None)

    def get_progress(self, sim_id: str) -> Dict:
        """Get current simulation progress."""
        state = self.sim_manager.get(sim_id)
        if not state:
            return {"error": f"Simulation {sim_id} not found"}

        result = {
            "sim_id": sim_id,
            "status": state.status.value,
            "current_round": state.current_round,
            "total_rounds": state.total_rounds,
            "progress_pct": round(state.current_round / state.total_rounds * 100, 1)
                if state.total_rounds > 0 else 0,
        }

        # Check if actions.jsonl exists and count lines
        actions_path = os.path.join(state.output_dir, "actions.jsonl")
        if os.path.exists(actions_path):
            with open(actions_path, "r", encoding="utf-8") as f:
                result["total_actions"] = sum(1 for _ in f)

        return result

    def get_actions(self, sim_id: str, limit: int = 200) -> list:
        """Get enriched simulation actions — prefers direct DB query over actions.jsonl.

        Data sources (in priority order):
        1. OASIS SQLite DB (oasis_simulation.db) — ground truth
        2. actions.jsonl — fallback for in-progress or legacy sims
        """
        state = self.sim_manager.get(sim_id)
        if not state:
            return []

        agent_names = self._load_agent_names(state.profiles_path)

        # Try DB-first approach
        db_path = os.path.join(state.output_dir, "oasis_simulation.db")
        if os.path.exists(db_path):
            try:
                return self._get_actions_from_db(db_path, agent_names, limit)
            except Exception as e:
                logger.warning(f"DB query failed, falling back to jsonl: {e}")

        # Fallback: actions.jsonl
        return self._get_actions_from_jsonl(state, agent_names, limit)

    def _get_actions_from_db(self, db_path: str, agent_names: dict, limit: int) -> list:
        """Query OASIS SQLite DB directly for posts, comments, likes.

        Uses bulk trace→content mapping to fill empty post/comment content.
        """
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # ── 0. Build trace content maps (bulk) ──
        post_trace_map, comment_trace_map = self._build_trace_content_maps(conn)

        # ── 1. Load all posts ──
        posts = []
        try:
            cursor = conn.execute(
                "SELECT post_id, user_id, content, created_at, "
                "num_likes, num_dislikes FROM post ORDER BY created_at"
            )
            for row in cursor:
                content = row["content"] or ""
                uid = row["user_id"]
                # Trace fallback: pop next content for this user
                if not content and uid in post_trace_map and post_trace_map[uid]:
                    content = post_trace_map[uid].pop(0)
                posts.append({
                    "action_type": "create_post",
                    "post_id": row["post_id"],
                    "agent_id": uid,
                    "agent_name": agent_names.get(uid, f"Agent {uid}"),
                    "content": content,
                    "num_likes": row["num_likes"] or 0,
                    "num_dislikes": row["num_dislikes"] or 0,
                    "timestamp": row["created_at"],
                })
        except Exception as e:
            logger.debug(f"Posts query: {e}")

        # ── 2. Load all comments ──
        all_comments = []
        try:
            cursor = conn.execute(
                "SELECT c.comment_id, c.post_id, c.user_id, c.content, c.created_at, "
                "p.user_id AS post_author_id "
                "FROM comment c LEFT JOIN post p ON c.post_id = p.post_id "
                "ORDER BY c.created_at"
            )
            for row in cursor:
                content = row["content"] or ""
                uid = row["user_id"]
                if not content and uid in comment_trace_map and comment_trace_map[uid]:
                    content = comment_trace_map[uid].pop(0)
                all_comments.append({
                    "action_type": "create_comment",
                    "comment_id": row["comment_id"],
                    "post_id": row["post_id"],
                    "agent_id": uid,
                    "agent_name": agent_names.get(uid, f"Agent {uid}"),
                    "content": content,
                    "post_author_name": agent_names.get(row["post_author_id"], "") if row["post_author_id"] is not None else "",
                    "timestamp": row["created_at"],
                })
        except Exception as e:
            logger.debug(f"Comments query: {e}")

        # ── 3. Load all likes ──
        all_likes = []
        try:
            cursor = conn.execute(
                "SELECT l.like_id, l.post_id, l.user_id, l.created_at "
                "FROM like l ORDER BY l.created_at"
            )
            for row in cursor:
                all_likes.append({
                    "action_type": "like_post",
                    "like_id": row["like_id"],
                    "post_id": row["post_id"],
                    "agent_id": row["user_id"],
                    "agent_name": agent_names.get(row["user_id"], f"Agent {row['user_id']}"),
                    "timestamp": row["created_at"],
                })
        except Exception as e:
            logger.debug(f"Likes query: {e}")

        conn.close()

        # ── 4. Build comment/like indexes per post_id ──
        comments_by_post = {}
        for c in all_comments:
            pid = c["post_id"]
            if pid not in comments_by_post:
                comments_by_post[pid] = []
            comments_by_post[pid].append({
                "agent_id": c["agent_id"],
                "agent_name": c["agent_name"],
                "content": c["content"],
                "timestamp": c["timestamp"],
            })

        like_counts = {}
        for lk in all_likes:
            pid = lk["post_id"]
            like_counts[pid] = like_counts.get(pid, 0) + 1

        # ── 5. Enrich posts with comments + likes ──
        for post in posts:
            pid = post["post_id"]
            post["num_comments"] = len(comments_by_post.get(pid, []))
            post["num_likes"] = like_counts.get(pid, post.get("num_likes", 0))
            post["comments"] = comments_by_post.get(pid, [])

        # ── 6. Filter empty-content posts (OASIS sign-up noise) ──
        posts_with_content = [p for p in posts if p.get("content", "").strip()]

        # ── 7. Return only posts with content (likes counted in num_likes) ──
        result = posts_with_content[:limit]

        filled_posts = sum(1 for p in posts if p.get("content"))
        filled_comments = sum(1 for c in all_comments if c.get("content"))
        logger.info(
            f"DB query: {len(posts)} posts ({filled_posts} with content), "
            f"{len(all_comments)} comments ({filled_comments} with content), "
            f"{len(all_likes)} likes"
        )
        return result

    @staticmethod
    def _build_trace_content_maps(conn) -> tuple:
        """Build user_id → [content_list] maps from the trace table.

        Loads ALL trace entries sorted by created_at, extracts content from
        the 'info' JSON field, and groups by user_id and action type (post/comment).
        The lists are in chronological order so pop(0) gives the next match.
        """
        post_map = {}    # user_id → [content, content, ...]
        comment_map = {}  # user_id → [content, content, ...]

        try:
            cursor = conn.execute(
                "SELECT user_id, action, info FROM trace ORDER BY created_at"
            )
            for row in cursor:
                uid = row["user_id"]
                action = str(row["action"] or "").upper()
                info_raw = row["info"]
                if not info_raw:
                    continue

                # Parse info JSON
                content = ""
                if isinstance(info_raw, str):
                    try:
                        info = json.loads(info_raw)
                        if isinstance(info, dict):
                            content = (info.get("content", "")
                                       or info.get("text", "")
                                       or info.get("post_content", "")
                                       or info.get("comment_content", ""))
                        else:
                            content = str(info_raw) if len(info_raw) > 10 else ""
                    except (json.JSONDecodeError, TypeError):
                        content = info_raw if len(info_raw) > 10 else ""

                if not content:
                    continue

                # Categorize by action type
                if "POST" in action and "COMMENT" not in action:
                    post_map.setdefault(uid, []).append(content)
                elif "COMMENT" in action:
                    comment_map.setdefault(uid, []).append(content)
                else:
                    # Unknown action type — add to posts as fallback
                    post_map.setdefault(uid, []).append(content)
        except Exception:
            pass

        return post_map, comment_map

    def _get_actions_from_jsonl(self, state, agent_names: dict, limit: int) -> list:
        """Fallback: read from actions.jsonl when DB is not available."""
        actions_path = os.path.join(state.output_dir, "actions.jsonl")
        if not os.path.exists(actions_path):
            return []

        raw_actions = []
        with open(actions_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        raw_actions.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        # Normalize action_types to lowercase
        for a in raw_actions:
            if "action_type" in a:
                a["action_type"] = (a["action_type"] or "").lower()

        # Count comments + likes per post_id
        comment_counts = {}
        like_counts = {}
        comments_by_post = {}
        for a in raw_actions:
            atype = a.get("action_type", "")
            pid = a.get("post_id")
            if pid is None:
                continue
            if atype == "create_comment":
                comment_counts[pid] = comment_counts.get(pid, 0) + 1
                if pid not in comments_by_post:
                    comments_by_post[pid] = []
                aid = a.get("agent_id", -1)
                comments_by_post[pid].append({
                    "agent_id": aid,
                    "agent_name": agent_names.get(aid, f"Agent {aid}"),
                    "content": self._extract_content(a),
                    "timestamp": a.get("timestamp"),
                })
            elif atype == "like_post":
                like_counts[pid] = like_counts.get(pid, 0) + 1

        # Enrich and filter
        enriched = []
        for a in raw_actions:
            atype = a.get("action_type", "")
            if atype in ("trace", "sign_up", "do_nothing"):
                continue
            aid = a.get("agent_id", -1)
            a["agent_name"] = agent_names.get(aid, f"Agent {aid}")
            if not a.get("content"):
                a["content"] = self._extract_content(a)
            if atype == "create_post" and a.get("post_id") is not None:
                pid = a["post_id"]
                a["num_comments"] = comment_counts.get(pid, 0)
                a["num_likes"] = like_counts.get(pid, 0)
                a["comments"] = comments_by_post.get(pid, [])
            enriched.append(a)
            if len(enriched) >= limit:
                break
        return enriched

    @staticmethod
    def _extract_content(action: dict) -> str:
        """Extract content from action, including from nested OASIS 'info' field."""
        # Direct content
        content = action.get("content", "")
        if content:
            return content

        # Try to extract from OASIS 'info' field (sometimes a JSON string)
        info = action.get("info")
        if info:
            if isinstance(info, str):
                try:
                    info = json.loads(info)
                except (json.JSONDecodeError, TypeError):
                    return info  # Return raw string as content
            if isinstance(info, dict):
                # OASIS may store content in various fields
                return (info.get("content", "")
                        or info.get("text", "")
                        or info.get("post_content", "")
                        or info.get("comment_content", ""))
        return ""


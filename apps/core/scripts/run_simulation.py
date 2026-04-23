"""
Run Simulation — OASIS framework with MiroFish config-aware loop.

MiroFish pattern features:
  - Time-based agent selection (period_multipliers × active_hours × activity_level)
  - Initial post injection (ManualAction at Round 0)
  - Simulated time: 1 round = minutes_per_round (default 60min)
  - Per-agent behavior: posting probability, active hours, influence
  - Crisis injection at trigger_round
  - Incremental DB action extraction
"""

# Fix Windows cp1252 encoding for subprocess stdout
import os, sys
os.environ["PYTHONIOENCODING"] = "utf-8"

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        import io
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )

import argparse
import asyncio
import csv
import json
import os
import random
import sqlite3
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Add parent dirs to path for OASIS imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Load env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# Bridge LLM_API_KEY → OPENAI_API_KEY (camel-ai requires OPENAI_API_KEY)
if os.getenv("LLM_API_KEY") and not os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.getenv("LLM_API_KEY")

# Check if oasis is available
oasis_path = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "oasis"
))
if os.path.exists(oasis_path):
    sys.path.insert(0, oasis_path)


# ============================================================
# TIME-BASED AGENT SELECTION (MiroFish pattern)
# ============================================================

def get_hour_multiplier(simulated_hour: int, time_config: dict) -> float:
    """
    Get activity multiplier for a given hour based on period_multipliers.
    MiroFish pattern: peak hours get ×1.5, off-peak get ×0.05, etc.

    1 round = time_config.minutes_per_round (default 60min = 1 hour)
    """
    period_multipliers = time_config.get("period_multipliers", [])

    if period_multipliers:
        for period in period_multipliers:
            hours = period.get("hours", [])
            if simulated_hour in hours:
                return period.get("multiplier", 1.0)
        return 1.0  # Default if hour not in any period

    # Fallback: simple peak/off-peak
    peak_hours = time_config.get("peak_hours", [19, 20, 21, 22])
    off_peak_hours = time_config.get("off_peak_hours", [0, 1, 2, 3, 4, 5])

    if simulated_hour in peak_hours:
        return 1.5
    elif simulated_hour in off_peak_hours:
        return 0.3
    return 1.0


# Track which agents have been activated (ensures all participate)
_activated_agents: set = set()


def select_active_agents(
    num_profiles: int,
    agent_configs: list,
    min_agents: int,
    max_agents: int,
    simulated_hour: int = 12,
    time_config: Optional[dict] = None,
) -> list:
    """
    Select active agents for this round using MiroFish time-based pattern.

    Factors:
    - period_multipliers → hour multiplier (×1.5 peak, ×0.05 low)
    - Per-agent active_hours → soft filter (outside hours = half probability)
    - Per-agent activity_level → probability of activation (floor 50%)
    - Fairness: all agents participate at least once per cycle
    - Small simulations (≤5 agents): ALL agents active every round
    """
    global _activated_agents
    time_config = time_config or {}

    if not agent_configs:
        return list(range(num_profiles))

    # Small simulations: ALL agents active every round (ensures rich interaction)
    if num_profiles <= 5:
        return list(range(num_profiles))

    # Get hour multiplier
    hour_mult = get_hour_multiplier(simulated_hour, time_config)

    # Compute target agent count — floor at 40% of agents for medium sims
    min_target = max(min_agents, int(num_profiles * 0.4), 3)
    base_max = max(min_target, max_agents)
    target_count = int(random.uniform(min_target, base_max) * max(hour_mult, 0.3))
    target_count = max(min_target, min(target_count, num_profiles))

    # Build candidate pool
    all_ids = list(range(num_profiles))

    # Reset tracking when all agents have been activated
    if _activated_agents.issuperset(set(all_ids)):
        _activated_agents.clear()

    candidates = []
    priority_candidates = []  # Agents who haven't been activated yet

    for ac in agent_configs:
        aid = ac.get("agent_id", 0)
        if aid >= num_profiles:
            continue

        active_hours = ac.get("active_hours", list(range(8, 23)))
        activity_level = max(0.5, ac.get("activity_level", 0.5))  # Floor 50%
        posting_prob = ac.get("posting_probability", 0.5)

        # Soft filter: outside active hours reduces probability by 30% (not 50%)
        if simulated_hour not in active_hours:
            activity_level *= 0.7

        # Combined probability — boosted floor
        combined_prob = activity_level * max(0.5, posting_prob)

        # Probabilistic activation — but floor at 30% chance
        if random.random() < max(combined_prob, 0.3):
            candidates.append(aid)
            if aid not in _activated_agents:
                priority_candidates.append(aid)

    # Ensure we always have candidates
    if not candidates:
        candidates = all_ids[:] if all_ids else [0]

    # Selection: prioritize agents who haven't been activated yet
    selected = []
    if priority_candidates:
        priority_count = min(len(priority_candidates), max(1, target_count // 2))
        selected.extend(random.sample(priority_candidates, priority_count))

    # Fill remaining from all candidates
    remaining = [c for c in candidates if c not in selected]
    fill_count = min(target_count - len(selected), len(remaining))
    if fill_count > 0:
        selected.extend(random.sample(remaining, fill_count))

    # Track activations
    _activated_agents.update(selected)

    return selected


# ============================================================
# INITIAL POSTS (MiroFish pattern: ManualAction)
# ============================================================

async def inject_initial_posts(env, event_config: dict, agent_names: Dict[int, str]):
    """
    Inject initial_posts using ManualAction (MiroFish pattern).
    All posts are batched in a single env.step() call.
    """
    try:
        from oasis import ActionType, ManualAction
    except ImportError:
        print("  [INIT] Cannot import oasis for initial post injection")
        return

    initial_posts = event_config.get("initial_posts", [])
    if not initial_posts:
        print("  [INIT] No initial posts to inject")
        return

    print(f"  [INIT] Injecting {len(initial_posts)} initial posts (ManualAction)...")

    initial_actions = {}
    for post in initial_posts:
        content = post.get("content", "")
        poster_id = post.get("poster_agent_id", 0)
        if poster_id is None:
            poster_id = 0
        if not content:
            continue

        try:
            agent = env.agent_graph.get_agent(poster_id)
            if agent in initial_actions:
                if not isinstance(initial_actions[agent], list):
                    initial_actions[agent] = [initial_actions[agent]]
                initial_actions[agent].append(ManualAction(
                    action_type=ActionType.CREATE_POST,
                    action_args={"content": content}
                ))
            else:
                initial_actions[agent] = ManualAction(
                    action_type=ActionType.CREATE_POST,
                    action_args={"content": content}
                )
            name = agent_names.get(poster_id, f'Agent_{poster_id}')
            print(f"    → [{name}]: {content[:80]}...")
        except Exception as e:
            print(f"    Warning: Failed to create action for agent {poster_id}: {e}")

    if initial_actions:
        await env.step(initial_actions)
        print(f"  [INIT] Published {len(initial_actions)} initial posts")


# ============================================================
# CRISIS INJECTION
# ============================================================

def load_crisis_config(crisis_path, scenario_index):
    """Load crisis scenario config."""
    with open(crisis_path, "r", encoding="utf-8") as f:
        scenarios = json.load(f)
    if scenario_index >= len(scenarios):
        scenario_index = 0
    scenario = scenarios[scenario_index]
    events = {}
    for event in scenario.get("events", []):
        trigger = event.get("trigger_round", 0)
        events[trigger] = event
    return scenario, events


# ============================================================
# DB EXPORT
# ============================================================

def export_actions_from_db(db_path, output_path):
    """Export all posts, comments, likes from OASIS SQLite DB to actions.jsonl."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    actions = []

    # Export posts
    try:
        cursor = conn.execute(
            "SELECT post_id, user_id, content, created_at, num_likes, num_dislikes "
            "FROM post ORDER BY created_at"
        )
        for row in cursor:
            actions.append({
                "action_type": "create_post",
                "post_id": row["post_id"],
                "agent_id": row["user_id"],
                "content": row["content"],
                "num_likes": row["num_likes"],
                "num_dislikes": row["num_dislikes"],
                "timestamp": row["created_at"],
            })
    except Exception as e:
        print(f"  Warning: cannot export posts: {e}")

    # Export comments
    try:
        cursor = conn.execute(
            "SELECT comment_id, post_id, user_id, content, created_at "
            "FROM comment ORDER BY created_at"
        )
        for row in cursor:
            actions.append({
                "action_type": "create_comment",
                "comment_id": row["comment_id"],
                "post_id": row["post_id"],
                "agent_id": row["user_id"],
                "content": row["content"],
                "timestamp": row["created_at"],
            })
    except Exception as e:
        print(f"  Warning: cannot export comments: {e}")

    # Export likes
    try:
        cursor = conn.execute(
            "SELECT like_id, post_id, user_id, created_at FROM like ORDER BY created_at"
        )
        for row in cursor:
            actions.append({
                "action_type": "like_post",
                "like_id": row["like_id"],
                "post_id": row["post_id"],
                "agent_id": row["user_id"],
                "timestamp": row["created_at"],
            })
    except Exception as e:
        print(f"  Warning: cannot export likes: {e}")

    # Export trace logs
    try:
        cursor = conn.execute("SELECT * FROM trace ORDER BY created_at")
        for row in cursor:
            row_dict = dict(row)
            actions.append({"action_type": "trace", **row_dict})
    except Exception:
        pass

    conn.close()

    actions.sort(key=lambda a: str(a.get("timestamp", "")))

    with open(output_path, "w", encoding="utf-8") as f:
        for action in actions:
            f.write(json.dumps(action, ensure_ascii=False, default=str) + "\n")

    return len(actions)


def _get_round_actions_rich(db_path, prev_counts, agent_names):
    """Query OASIS SQLite for new actions with rich context (JOINs).

    Returns actions with agent_name, post_content, post_author_name
    for all action types: posts, comments, likes, follows, reposts.
    """
    new_actions = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # ── Posts (with trace fallback for content) ──
        cursor = conn.execute(
            "SELECT p.post_id, p.user_id, p.content, p.created_at "
            "FROM post p ORDER BY p.created_at "
            f"LIMIT -1 OFFSET {prev_counts['post']}"
        )
        for row in cursor:
            aid = row["user_id"]
            content = row["content"] or ""

            # If content is empty, try to get it from trace table
            if not content:
                try:
                    trace_row = conn.execute(
                        "SELECT info FROM trace WHERE user_id=? AND action LIKE '%post%' "
                        "ORDER BY created_at DESC LIMIT 1",
                        (aid,)
                    ).fetchone()
                    if trace_row and trace_row["info"]:
                        info = trace_row["info"]
                        if isinstance(info, str):
                            try:
                                info = json.loads(info)
                            except (json.JSONDecodeError, TypeError):
                                content = info  # Use raw string
                        if isinstance(info, dict):
                            content = (info.get("content", "")
                                       or info.get("text", "")
                                       or info.get("post_content", ""))
                except Exception:
                    pass

            new_actions.append({
                "action_type": "CREATE_POST",
                "agent_id": aid,
                "agent_name": agent_names.get(aid, f"Agent_{aid}"),
                "post_id": row["post_id"],
                "content": content,
                "timestamp": row["created_at"],
            })
        prev_counts["post"] = conn.execute("SELECT count(*) FROM post").fetchone()[0]

        # ── Comments (JOIN post for parent context) ──
        cursor = conn.execute(
            "SELECT c.comment_id, c.post_id, c.user_id, c.content, c.created_at, "
            "       p.content AS post_content, p.user_id AS post_author_id "
            "FROM comment c LEFT JOIN post p ON c.post_id = p.post_id "
            "ORDER BY c.created_at "
            f"LIMIT -1 OFFSET {prev_counts['comment']}"
        )
        for row in cursor:
            aid = row["user_id"]
            post_author_id = row["post_author_id"]
            new_actions.append({
                "action_type": "CREATE_COMMENT",
                "agent_id": aid,
                "agent_name": agent_names.get(aid, f"Agent_{aid}"),
                "post_id": row["post_id"],
                "content": row["content"],
                "post_content": (row["post_content"] or "")[:200],
                "post_author_name": agent_names.get(post_author_id, f"Agent_{post_author_id}") if post_author_id is not None else "",
                "timestamp": row["created_at"],
            })
        prev_counts["comment"] = conn.execute("SELECT count(*) FROM comment").fetchone()[0]

        # ── Likes (JOIN post for liked content + author) ──
        cursor = conn.execute(
            "SELECT l.like_id, l.post_id, l.user_id, l.created_at, "
            "       p.content AS post_content, p.user_id AS post_author_id "
            "FROM like l LEFT JOIN post p ON l.post_id = p.post_id "
            "ORDER BY l.created_at "
            f"LIMIT -1 OFFSET {prev_counts['like']}"
        )
        for row in cursor:
            aid = row["user_id"]
            post_author_id = row["post_author_id"]
            new_actions.append({
                "action_type": "LIKE_POST",
                "agent_id": aid,
                "agent_name": agent_names.get(aid, f"Agent_{aid}"),
                "post_id": row["post_id"],
                "post_content": (row["post_content"] or "")[:200],
                "post_author_name": agent_names.get(post_author_id, f"Agent_{post_author_id}") if post_author_id is not None else "",
                "timestamp": row["created_at"],
            })
        prev_counts["like"] = conn.execute("SELECT count(*) FROM like").fetchone()[0]

        # ── Follow / Repost (from trace table) ──
        cursor = conn.execute(
            "SELECT user_id, action, info, created_at FROM trace "
            "ORDER BY created_at "
            f"LIMIT -1 OFFSET {prev_counts['trace']}"
        )
        for row in cursor:
            action_val = str(row["action"]).upper()
            aid = row["user_id"]
            info = {}
            try:
                info = json.loads(row["info"]) if row["info"] else {}
            except Exception:
                pass

            if "FOLLOW" in action_val:
                target_id = info.get("followee_id", info.get("target_user_id"))
                new_actions.append({
                    "action_type": "FOLLOW",
                    "agent_id": aid,
                    "agent_name": agent_names.get(aid, f"Agent_{aid}"),
                    "target_user_id": target_id,
                    "target_user_name": agent_names.get(target_id, f"Agent_{target_id}") if target_id is not None else "",
                    "timestamp": row["created_at"],
                })
            elif "REPOST" in action_val:
                target_post_id = info.get("post_id")
                post_content, post_author = "", ""
                if target_post_id is not None:
                    try:
                        pr = conn.execute(
                            "SELECT content, user_id FROM post WHERE post_id=?",
                            (target_post_id,)
                        ).fetchone()
                        if pr:
                            post_content = (pr["content"] or "")[:200]
                            post_author = agent_names.get(pr["user_id"], f"Agent_{pr['user_id']}")
                    except Exception:
                        pass
                new_actions.append({
                    "action_type": "REPOST",
                    "agent_id": aid,
                    "agent_name": agent_names.get(aid, f"Agent_{aid}"),
                    "post_id": target_post_id,
                    "post_content": post_content,
                    "post_author_name": post_author,
                    "timestamp": row["created_at"],
                })
        prev_counts["trace"] = conn.execute("SELECT count(*) FROM trace").fetchone()[0]

        conn.close()
    except Exception:
        pass
    return new_actions


# ============================================================
# MAIN OASIS SIMULATION (MiroFish config-aware)
# ============================================================

async def run_oasis_simulation(args):
    """Run simulation using real OASIS framework — MiroFish config-aware."""
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType, ModelType

    import oasis
    from oasis import (
        ActionType,
        LLMAction,
        ManualAction,
        generate_twitter_agent_graph,
    )

    # ── Load full sim config ──
    sim_config = json.load(open(args.config, "r", encoding="utf-8"))

    # Parse time_config (MiroFish Step 03)
    time_config = sim_config.get("time_config", {})
    total_sim_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 60)
    total_rounds = time_config.get("total_rounds", 24)
    min_agents = time_config.get("agents_per_round_min", 2)
    max_agents = time_config.get("agents_per_round_max", 10)

    # Parse event_config (MiroFish Step 04)
    event_config = sim_config.get("event_config", {})

    # Parse cognitive_toggles (controls which cognitive modules are active)
    cog_toggles = sim_config.get("cognitive_toggles", {})
    USE_MEMORY = cog_toggles.get("enable_agent_memory", True)
    USE_MBTI = cog_toggles.get("enable_mbti_modifiers", True)
    USE_INTEREST_DRIFT = cog_toggles.get("enable_interest_drift", True)
    USE_REFLECTION = cog_toggles.get("enable_reflection", True)
    USE_KG = cog_toggles.get("enable_graph_cognition", False)
    print(f"SIM_CONFIG: Cognitive toggles: memory={USE_MEMORY}, mbti={USE_MBTI}, "
          f"interest_drift={USE_INTEREST_DRIFT}, reflection={USE_REFLECTION}, kg={USE_KG}")

    # Parse agent behavior configs (MiroFish Step 03)
    # These can be in sim_config or in profiles — build merged lookup
    agent_configs = []

    # Load profiles and build agent_configs from CSV
    profiles = []
    with open(args.profiles, "r", encoding="utf-8") as pf:
        reader = csv.DictReader(pf)
        for idx, row in enumerate(reader):
            profiles.append(row)
            # Build per-agent config from CSV fields
            try:
                active_hours = json.loads(row.get("active_hours", "[]"))
            except (json.JSONDecodeError, TypeError):
                active_hours = list(range(8, 23))

            agent_configs.append({
                "agent_id": idx,
                "entity_name": row.get("name", f"Agent_{idx}"),
                "entity_type": row.get("entity_type", row.get("role", "Entity")),
                "stance_label": row.get("stance_label", "neutral"),
                "activity_level": float(row.get("activity_level", 0.5)),
                "posting_probability": float(row.get("posting_probability", 0.5)),
                "comments_per_time": float(row.get("comments_per_time", 0.5)),
                "response_delay_min": int(row.get("response_delay_min", 5)),
                "response_delay_max": int(row.get("response_delay_max", 30)),
                "active_hours": active_hours,
                "influence_score": float(row.get("influence_score", 0.5)),
                "sentiment_bias": float(row.get("sentiment_bias", 0.0)),
            })

    # Build agent name mapping
    agent_names = {idx: ac["entity_name"] for idx, ac in enumerate(agent_configs)}

    # Crisis config
    scenario, crisis_events = load_crisis_config(args.crisis, args.scenario_index)

    # ── Create model ──
    openai_model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=ModelType.GPT_4O_MINI,
    )

    # Define available actions (QUOTE_POST for agent interaction)
    available_actions = [
        ActionType.CREATE_POST,
        ActionType.LIKE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.REPOST,
        ActionType.DO_NOTHING,
        ActionType.FOLLOW,
    ]

    # Generate agent graph from OASIS-compatible CSV
    print(f"SIM_SETUP: Loading {len(profiles)} agents from {args.profiles}")
    agent_graph = await generate_twitter_agent_graph(
        profile_path=args.profiles,
        model=openai_model,
        available_actions=available_actions,
    )

    # Database path
    db_path = os.path.join(args.output_dir, "oasis_simulation.db")
    os.environ["OASIS_DB_PATH"] = os.path.abspath(db_path)
    if os.path.exists(db_path):
        os.remove(db_path)

    # Create OASIS environment with tuned RecSys
    # Default TWITTER preset uses twhin-bert with max_rec_post_len=2 → agents only
    # see 2-5 posts → very low interaction. Custom Platform fixes this.
    print(f"SIM_SETUP: Creating OASIS environment (Reddit RecSys, optimized)")
    from oasis.social_platform.channel import Channel as OasisChannel
    from oasis.social_platform.platform import Platform as OasisPlatform

    oasis_channel = OasisChannel()
    custom_platform = OasisPlatform(
        db_path=db_path,
        channel=oasis_channel,
        recsys_type="reddit",           # Lightweight, no ML models needed
        refresh_rec_post_count=10,       # Show 10 posts from RecSys per refresh (was 2)
        max_rec_post_len=20,             # Buffer 20 posts per user in rec table (was 2)
        following_post_count=5,          # Top 5 posts from followed users (was 3)
    )

    env = oasis.make(
        agent_graph=agent_graph,
        platform=custom_platform,
        database_path=db_path,
    )
    await env.reset()

    num_agents = agent_graph.get_num_nodes()

    # Log config summary
    print(f"SIM_CONFIG: {total_sim_hours}h simulation, {minutes_per_round}min/round, "
          f"{total_rounds} rounds, {num_agents} agents ({min_agents}-{max_agents}/round)")
    print(f"SIM_CONFIG: Period multipliers: {len(time_config.get('period_multipliers', []))}")
    print(f"SIM_CONFIG: Initial posts: {len(event_config.get('initial_posts', []))}")
    print(f"SIM_CONFIG: Hot topics: {event_config.get('hot_topics', [])}")
    print(f"SIM_START: agents={num_agents}, rounds={total_rounds}, scenario={scenario['name']}")
    sys.stdout.flush()

    # ── Agent Memory Setup (gated by cognitive toggle) ──
    memory_mgr = None
    if USE_MEMORY:
        try:
            from app.services.agent_memory import AgentMemoryManager
            memory_mgr = AgentMemoryManager(sim_id=args.sim_id)
            for idx, row in enumerate(profiles):
                memory_mgr.register_agent(
                    agent_id=str(idx),
                    name=row.get("name", f"Agent_{idx}"),
                    role=row.get("entity_type", row.get("role", "Unknown"))[:80],
                )
            print(f"  [MEMORY] Registered {len(profiles)} agents in FalkorDB memory graph")
        except Exception as e:
            print(f"  [MEMORY] Warning: Agent memory not available ({e})")
            memory_mgr = None
    else:
        print(f"  [MEMORY] Agent memory DISABLED by cognitive toggle")

    # ── Dynamic KG Retriever Setup (gated by cognitive toggle) ──
    kg_retriever = None
    if USE_KG:
        try:
            from app.services.kg_retriever import KGRetriever
            kg_retriever = KGRetriever()
            print(f"  [KG_RAG] Dynamic KG retriever initialized (Graphiti hybrid search + fallback)")
        except Exception as e:
            print(f"  [KG_RAG] Warning: KG retriever not available ({e})")
            kg_retriever = None
    else:
        print(f"  [KG_RAG] Knowledge Graph cognition DISABLED by cognitive toggle")
    sys.stdout.flush()

    # ── ROUND 0: Inject Initial Posts (MiroFish Step 04) ──
    await inject_initial_posts(env, event_config, agent_names)
    sys.stdout.flush()

    # Track previous action counts for delta detection
    prev_action_counts = {"post": 0, "comment": 0, "like": 0, "trace": 0}

    # Open actions.jsonl for incremental writing (realtime)
    actions_path = os.path.join(args.output_dir, "actions.jsonl")
    actions_file = open(actions_path, "w", encoding="utf-8")

    # ── Simulation Loop ──
    for round_num in range(1, total_rounds + 1):
        # Map round → simulated hour (1 round = minutes_per_round of real time)
        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24
        hour_mult = get_hour_multiplier(simulated_hour, time_config)

        print(f"ROUND:{round_num}")
        print(f"  [TIME] Simulated hour: {simulated_hour}:00, multiplier: ×{hour_mult}")
        sys.stdout.flush()

        # ── Select Active Agents (MiroFish time-based) ──
        active_indices = select_active_agents(
            num_profiles=num_agents,
            agent_configs=agent_configs,
            min_agents=min_agents,
            max_agents=max_agents,
            simulated_hour=simulated_hour,
            time_config=time_config,
        )

        active_names = [agent_names.get(i, f"Agent_{i}") for i in active_indices]
        print(f"  [AGENTS] {len(active_indices)}/{num_agents} active: {', '.join(active_names[:5])}{'...' if len(active_names) > 5 else ''}")

        # ── Recall & Inject Memories ──
        if memory_mgr and round_num > 1:
            try:
                for idx in active_indices:
                    _, agent = list(env.agent_graph.get_agents())[idx] if idx < num_agents else (None, None)
                    if agent is None:
                        continue
                    memory_context = memory_mgr.get_agent_memory_summary(str(idx), limit=5)
                    if memory_context and hasattr(agent, 'system_message') and agent.system_message:
                        base = agent.system_message.content
                        marker = "Bộ nhớ của bạn từ các round trước:"
                        if marker not in base:
                            agent.system_message.content = base + "\n\n" + memory_context
                        else:
                            agent.system_message.content = base.split(marker)[0] + memory_context
                print(f"  [MEMORY] Injected memories into {len(active_indices)} active agents")
            except Exception as e:
                print(f"  [MEMORY] Recall warning: {e}")

        # ── Dynamic KG Retrieval ──
        if kg_retriever and round_num > 1:
            try:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT content FROM post ORDER BY created_at DESC LIMIT 10"
                )
                recent_posts = [row["content"] for row in cursor if row["content"]]
                conn.close()

                if recent_posts:
                    feed_text = " ".join(recent_posts[:5])
                    kg_context = await kg_retriever.retrieve_for_context(feed_text, limit=5)
                    if kg_context:
                        kg_marker = "[KG] Thông tin liên quan:"
                        for idx in active_indices:
                            try:
                                _, agent = list(env.agent_graph.get_agents())[idx]
                                if hasattr(agent, 'system_message') and agent.system_message:
                                    base = agent.system_message.content
                                    if kg_marker in base:
                                        base = base.split(kg_marker)[0].rstrip()
                                    agent.system_message.content = base + "\n\n" + kg_context
                            except Exception:
                                pass
                        print(f"  [KG_RAG] Dynamic context injected based on {len(recent_posts)} posts")
            except Exception as e:
                print(f"  [KG_RAG] Retrieval warning: {e}")

        # ── Crisis Check ──
        if round_num in crisis_events:
            event = crisis_events[round_num]
            headline = event.get(
                "news_headline",
                f"⚠️ BREAKING: {event.get('name', 'Crisis Event')}"
            )
            crisis_action = {
                env.agent_graph.get_agent(0): [
                    ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={
                            "content": (
                                f"{headline}\n\n"
                                f"{event.get('description', '')}\n\n"
                                f"Severity: {event.get('severity', 'medium')}"
                            )
                        },
                    )
                ]
            }
            await env.step(crisis_action)
            print(f"  [CRISIS] INJECTED: {event.get('name', '')} ({event.get('severity', '')})")

        # ── Active Agents Decide via LLM (only selected agents) ──
        agent_actions = {}
        for idx in active_indices:
            try:
                agent = env.agent_graph.get_agent(idx)
                agent_actions[agent] = LLMAction()
            except Exception:
                pass

        if not agent_actions:
            print(f"  [WARN] No active agents for round {round_num}")
            continue

        await env.step(agent_actions)
        print(f"  [OK] Round {round_num} complete ({len(agent_actions)} agents acted)")
        sys.stdout.flush()

        # ── Write Actions Incrementally + Store Memories ──
        try:
            new_actions = _get_round_actions_rich(db_path, prev_action_counts, agent_names)
            for act in new_actions:
                act["round"] = round_num
                actions_file.write(json.dumps(act, ensure_ascii=False, default=str) + "\n")
            actions_file.flush()
            if new_actions:
                print(f"  [ACTIONS] {len(new_actions)} actions written to actions.jsonl")

            # Store memories (only for content-bearing actions)
            if memory_mgr:
                stored = 0
                for act in new_actions:
                    aidx = act.get("agent_id", 0)
                    cnt = act.get("content", "")
                    if cnt and aidx < len(profiles):
                        prof = profiles[aidx]
                        memory_mgr.store_memory(
                            agent_id=str(aidx),
                            agent_name=prof.get("name", f"Agent_{aidx}"),
                            agent_role=prof.get("entity_type", prof.get("role", ""))[:80],
                            round_num=round_num,
                            action_type=act.get("action_type", "unknown"),
                            content=cnt,
                            context=scenario.get("name", ""),
                        )
                        stored += 1
                if stored:
                    print(f"  [MEMORY] Stored {stored} memories for round {round_num}")
        except Exception as e:
            print(f"  [ACTIONS/MEMORY] Warning: {e}")

    # ── Close environment ──
    await env.close()

    # ── Close incremental actions file ──
    actions_file.close()
    action_count = sum(1 for _ in open(actions_path, "r", encoding="utf-8"))

    # ── Memory stats ──
    if memory_mgr:
        try:
            stats = memory_mgr.get_memory_stats()
            print(f"MEMORY_STATS: {json.dumps(stats)}")
            stats_path = os.path.join(args.output_dir, "memory_stats.json")
            with open(stats_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  [MEMORY] Stats warning: {e}")

    print(f"SIM_COMPLETE: {action_count} actions exported to {actions_path}")
    sys.stdout.flush()


# ── CLI ──
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EcoSim OASIS Simulation Runner")
    parser.add_argument("--sim-id", required=True)
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--crisis", required=True)
    parser.add_argument("--scenario-index", type=int, default=0)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    asyncio.run(run_oasis_simulation(args))

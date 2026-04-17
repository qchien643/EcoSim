"""
EcoSim -> OASIS Reddit Simulation + FalkorDB Graph Memory
Run Reddit simulation with EcoSim agents, write interactions to FalkorDB knowledge graph.

Usage (from oasis venv):
  .venv\Scripts\python.exe run_simulation.py
"""
import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from collections import defaultdict

# Fix Windows console encoding for Vietnamese text
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ==============================================================
# 1. Load .env config
# ==============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ECOSIM_ROOT = os.path.dirname(SCRIPT_DIR)  # EcoSim/
ENV_PATH = os.path.join(ECOSIM_ROOT, ".env")

def load_dotenv(path):
    """Simple .env loader -- no external dependency needed."""
    if not os.path.exists(path):
        print(f"WARNING: .env not found at {path}")
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

load_dotenv(ENV_PATH)
print(f"[CONFIG] Loaded from: {ENV_PATH}")

# Map EcoSim config -> OASIS/OpenAI env vars
api_key = os.environ.get("LLM_API_KEY", "")
if api_key:
    os.environ["OPENAI_API_KEY"] = api_key

base_url = os.environ.get("LLM_BASE_URL", "")
if base_url:
    os.environ["OPENAI_API_BASE_URL"] = base_url

model_name = os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")

# FalkorDB config
FALKOR_HOST = os.environ.get("FALKORDB_HOST", "localhost")
FALKOR_PORT = int(os.environ.get("FALKORDB_PORT", "6379"))
ENABLE_GRAPH = os.environ.get("ENABLE_GRAPH_MEMORY", "true").lower() in ("true", "1", "yes")

# ==============================================================
# 2. CLI args + Paths
# ==============================================================
import argparse
sim_parser = argparse.ArgumentParser(add_help=False)
sim_parser.add_argument("--group-id", default=None, help="Shared graph ID")
sim_parser.add_argument("--sim-dir", default=None, help="Simulation output directory")
sim_args, _ = sim_parser.parse_known_args()

# Resolve sim directory and config
SIM_DIR_ARG = sim_args.sim_dir
SIM_CONFIG = {}
NUM_ROUNDS = 3  # default

if SIM_DIR_ARG and os.path.isdir(SIM_DIR_ARG):
    config_path = os.path.join(SIM_DIR_ARG, "simulation_config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            SIM_CONFIG = json.load(f)
        NUM_ROUNDS = SIM_CONFIG.get("num_rounds", 3)
        print(f"   Loaded config from {config_path} (rounds={NUM_ROUNDS})")

# Profile path: prefer sim_dir/profiles.json, then backend default
if SIM_DIR_ARG and os.path.exists(os.path.join(SIM_DIR_ARG, "profiles.json")):
    PROFILE_PATH = os.path.join(SIM_DIR_ARG, "profiles.json")
else:
    PROFILE_PATH = os.path.join(ECOSIM_ROOT, "backend", "test_output", "test_profiles.json")

# Put DB in sim output dir when launched via API (--sim-dir),
# fallback to oasis/data/ for standalone runs.
if SIM_DIR_ARG and os.path.isdir(SIM_DIR_ARG):
    DB_PATH = os.path.join(SIM_DIR_ARG, "oasis_simulation.db")
else:
    DB_PATH = os.path.join(SCRIPT_DIR, "data", "ecosim_simulation.db")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
    print(f"[CLEAN]  Removed old database: {DB_PATH}")

# ==============================================================
# 3. Verify profiles
# ==============================================================
with open(PROFILE_PATH, "r", encoding="utf-8") as f:
    profiles = json.load(f)

print(f"[LIST] Loaded {len(profiles)} agent profiles:")
for i, p in enumerate(profiles):
    print(f"   [{i}] {p['username']} -- {p['realname']} ({p['age']}y, {p['gender']}, {p['mbti']})")
print()

# Build agent_id -> name mapping for graph memory
AGENT_NAMES = {i: p["realname"] for i, p in enumerate(profiles)}

# ==============================================================
# 4. OASIS imports
# ==============================================================
from camel.models import ModelFactory
from camel.types import ModelPlatformType, ModelType

import oasis
from oasis import ActionType, ManualAction, generate_reddit_agent_graph

# Interest-based feed recommendation
from interest_feed import (
    PostIndexer, EngagementTracker, should_post, build_interest_text,
    get_feed_size, update_rec_table_with_interests,
    decide_agent_actions,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def read_new_traces(db_path: str, last_trace_count: int) -> list:
    """Read new traces from SQLite since last check."""
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute(
            "SELECT user_id, action, info, created_at FROM trace "
            "ORDER BY rowid LIMIT -1 OFFSET ?",
            (last_trace_count,),
        )
        rows = c.fetchall()
        conn.close()
        return [
            {
                "user_id": r[0],
                "action_type": r[1],
                "info": r[2],
                "timestamp": r[3],
            }
            for r in rows
        ]
    except Exception as e:
        logging.getLogger("ecosim").warning("Failed to read traces: %s", e)
        return []


def _enrich_trace_for_kg(trace: dict, db_path: str, agent_names: dict):
    """Enrich a trace with post content + author for KG episodes.

    For 'like_post': adds post_content, post_author_name, post_author_id.
    For 'create_comment': adds post_content, post_author_name, post_author_id
                          (of the parent post being commented on).

    This ensures KG episodes contain rich, agent-specific context instead
    of bare post IDs like 'Agent X liked post #2'.
    """
    action_type = trace.get("action_type", "")
    info = trace.get("info", {})
    if isinstance(info, str):
        try:
            info = json.loads(info)
            trace["info"] = info
        except (json.JSONDecodeError, TypeError):
            return
    if not isinstance(info, dict):
        return

    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        if action_type == "like_post":
            post_id = info.get("post_id")
            if post_id is not None:
                c.execute(
                    "SELECT content, user_id FROM post WHERE post_id = ?",
                    (post_id,),
                )
                row = c.fetchone()
                if row:
                    info["post_content"] = row[0][:500] if row[0] else ""
                    info["post_author_id"] = row[1]
                    info["post_author_name"] = agent_names.get(
                        row[1], f"Agent {row[1]}"
                    )

        elif action_type == "create_comment":
            # Resolve comment_id → post_id if needed
            post_id = info.get("post_id")
            if post_id is None:
                comment_id = info.get("comment_id")
                if comment_id is not None:
                    c.execute(
                        "SELECT post_id FROM comment WHERE comment_id = ?",
                        (comment_id,),
                    )
                    crow = c.fetchone()
                    if crow:
                        post_id = crow[0]
                        info["post_id"] = post_id

            # Now lookup the parent post content + author
            if post_id is not None:
                c.execute(
                    "SELECT content, user_id FROM post WHERE post_id = ?",
                    (post_id,),
                )
                row = c.fetchone()
                if row:
                    info["post_content"] = row[0][:500] if row[0] else ""
                    info["post_author_id"] = row[1]
                    info["post_author_name"] = agent_names.get(
                        row[1], f"Agent {row[1]}"
                    )

        elif action_type == "dislike_post":
            post_id = info.get("post_id")
            if post_id is not None:
                c.execute(
                    "SELECT content, user_id FROM post WHERE post_id = ?",
                    (post_id,),
                )
                row = c.fetchone()
                if row:
                    info["post_content"] = row[0][:500] if row[0] else ""
                    info["post_author_id"] = row[1]
                    info["post_author_name"] = agent_names.get(
                        row[1], f"Agent {row[1]}"
                    )

        conn.close()
    except Exception as e:
        logging.getLogger("ecosim").debug("Trace enrichment error: %s", e)


async def main():
    # ----------------------------------------------------------
    # 4a. LLM Model
    # ----------------------------------------------------------
    if not os.environ.get("OPENAI_API_KEY"):
        print("[X] No API key found! Check .env file at:", ENV_PATH)
        sys.exit(1)

    print(f"[BOT] Creating LLM model ({model_name})...")
    model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=ModelType.GPT_4O_MINI,
    )

    # ----------------------------------------------------------
    # 4b. Agent Graph tu EcoSim profiles
    # ----------------------------------------------------------
    print("[BRAIN] Generating Reddit agent graph from EcoSim profiles...")
    agent_graph = await generate_reddit_agent_graph(
        profile_path=PROFILE_PATH,
        model=model,
        available_actions=ActionType.get_default_reddit_actions(),
    )
    print(f"   [OK] Created {agent_graph.get_num_nodes()} agents")

    # ----------------------------------------------------------
    # 4c. Create Environment
    # ----------------------------------------------------------
    print(f"[WEB] Creating OASIS Reddit environment...")
    print(f"   Database: {DB_PATH}")
    env = oasis.make(
        agent_graph=agent_graph,
        platform=oasis.DefaultPlatformType.REDDIT,
        database_path=DB_PATH,
    )

    # ----------------------------------------------------------
    # 5. FalkorDB Graph Memory (optional)
    # ----------------------------------------------------------
    graph_updater = None
    sim_id = sim_args.group_id or f"ecosim_{uuid.uuid4().hex[:8]}"

    if ENABLE_GRAPH:
        try:
            from falkor_graph_memory import FalkorGraphMemoryUpdater
            graph_updater = FalkorGraphMemoryUpdater(
                simulation_id=sim_id,
                falkor_host=FALKOR_HOST,
                falkor_port=FALKOR_PORT,
                batch_size=5,
                flush_interval=10.0,
                agent_names=AGENT_NAMES,
            )
            graph_updater.start()
            print(f"[BRAIN] FalkorDB graph memory ENABLED (sim_id={sim_id})")
            print(f"   FalkorDB: falkor://{FALKOR_HOST}:{FALKOR_PORT}")
        except ImportError:
            print("[WARN]  graphiti-core not installed -- graph memory disabled")
            print("   Install: pip install graphiti-core[falkordb]")
            graph_updater = None
        except Exception as e:
            print(f"[WARN]  FalkorDB connection failed: {e} -- graph memory disabled")
            graph_updater = None
    else:
        print("[INFO]  Graph memory disabled (set ENABLE_GRAPH_MEMORY=true to enable)")

    # ----------------------------------------------------------
    # 5b. Graph Cognitive Helper (reads from FalkorDB)
    # ----------------------------------------------------------
    graph_helper = None
    if SIM_CONFIG.get("enable_graph_cognition", False) and graph_updater:
        try:
            from agent_cognition import GraphCognitiveHelper
            graph_helper = GraphCognitiveHelper(
                falkor_host=FALKOR_HOST,
                falkor_port=FALKOR_PORT,
                group_id=sim_id,
            )
            print("[COGNITION] Graph Cognition ENABLED (reads FalkorDB for social context)")
        except Exception as e:
            print(f"[WARN] Graph Cognition init failed: {e}")
            graph_helper = None
    elif SIM_CONFIG.get("enable_graph_cognition", False):
        print("[WARN] Graph Cognition requested but FalkorDB unavailable — skipped")

    # ----------------------------------------------------------
    # 6. Reset (start platform + sign up agents)
    # ----------------------------------------------------------
    # Initialize interest-based feed recommendation
    post_indexer = PostIndexer()
    engagement_tracker = EngagementTracker()
    print("[STATS] Interest-based feed + engagement decay initialized (ChromaDB)")

    # Initialize agent memory (Phase 1 cognitive enhancement)
    agent_memory = None
    if SIM_CONFIG.get("enable_agent_memory", False):
        from agent_cognition import AgentMemory
        agent_memory = AgentMemory(num_agents=len(profiles))
        print("[COGNITION] Agent Memory ENABLED (round buffer, max 5 rounds)")
    else:
        print("[COGNITION] Agent Memory disabled (set enable_agent_memory=true)")

    # Initialize MBTI behavioral modifiers (Phase 2 cognitive enhancement)
    mbti_modifiers = {}  # agent_id → {post_mult, comment_mult, like_mult, ...}
    if SIM_CONFIG.get("enable_mbti_modifiers", False):
        from agent_cognition import get_behavior_modifiers
        for i, p in enumerate(profiles):
            mbti_modifiers[i] = get_behavior_modifiers(p.get("mbti", ""))
        print(f"[COGNITION] MBTI Modifiers ENABLED for {len(mbti_modifiers)} agents")
    else:
        from agent_cognition import get_behavior_modifiers
        for i in range(len(profiles)):
            mbti_modifiers[i] = get_behavior_modifiers("")  # all 1.0
        print("[COGNITION] MBTI Modifiers disabled (set enable_mbti_modifiers=true)")

    # Initialize interest drift tracker (Phase 3 — Weighted Interest Vector)
    interest_tracker = None
    if SIM_CONFIG.get("enable_interest_drift", False):
        from agent_cognition import InterestVectorTracker
        interest_tracker = InterestVectorTracker()
        # Initialize interest vectors for all agents from profiles
        for _aid, _prof in enumerate(profiles):
            interest_tracker.initialize_agent(_aid, _prof)
            _traits = interest_tracker.get_traits(_aid)
            if _aid < 3 or _aid == SIM_CONFIG.get("tracked_agent_id", -1):
                _top = interest_tracker.get_top_interests(_aid, 3)
                _top_str = ", ".join(f"{kw}({w:.1f})" for kw, w in _top)
                print(f"   Agent {_aid} ({_prof.get('mbti','?')}): [{_top_str}]")
        print(f"[COGNITION] Interest Vector ENABLED ({len(profiles)} agents initialized)")
    else:
        print("[COGNITION] Interest Drift disabled (set enable_interest_drift=true)")

    # Initialize reflection engine (Phase 4 cognitive enhancement)
    reflection = None
    if SIM_CONFIG.get("enable_reflection", False):
        if agent_memory:
            from agent_cognition import AgentReflection
            refl_interval = SIM_CONFIG.get("reflection_interval", 3)
            reflection = AgentReflection(interval=refl_interval)
            print(f"[COGNITION] Reflection ENABLED (every {refl_interval} rounds, persona evolution)")
        else:
            print("[COGNITION] Reflection SKIPPED — requires Agent Memory (enable_agent_memory=true)")
    else:
        print("[COGNITION] Reflection disabled (set enable_reflection=true)")

    # Monkey-patch the platform's update_rec_table to use our interest-based
    # recommendations instead of the built-in rec_sys_reddit (which gives ALL
    # posts to ALL users equally). This is called internally by env.step().
    _original_update_rec = env.platform.update_rec_table

    async def _interest_based_update_rec():
        """Custom rec table update: index new posts + personalized feed."""
        # Re-index all posts from DB
        post_indexer.index_from_db(DB_PATH)
        if post_indexer.count > 0:
            update_rec_table_with_interests(
                DB_PATH, post_indexer, profiles,
                interest_vectors=interest_tracker,
            )
        else:
            # Fallback to default if no posts indexed yet
            await _original_update_rec()

    env.platform.update_rec_table = _interest_based_update_rec
    print("   Patched Platform.update_rec_table -> interest-based recsys")

    print("\n[START] Resetting environment (signing up agents)...")
    await env.reset()
    print("   [OK] All agents signed up!")

    trace_count = 0  # Track traces for delta detection

    # ----------------------------------------------------------
    # 7. Seed Post (ManualAction) -- Campaign content
    # ----------------------------------------------------------
    # Load campaign context for seed post
    seed_content = ""
    if SIM_DIR_ARG:
        ctx_file = os.path.join(SIM_DIR_ARG, "campaign_context.txt")
        if os.path.exists(ctx_file):
            with open(ctx_file, "r", encoding="utf-8") as f:
                seed_content = f.read().strip()
    if not seed_content:
        seed_content = SIM_CONFIG.get("campaign_context", "Welcome to the discussion! Share your thoughts.")

    print(f"\n{'='*60}")
    print("  SEED POST (Campaign Injection)")
    print(f"{'='*60}")
    seed_preview = seed_content[:200].replace("\n", " ")
    print(f"   Content: {seed_preview}...")
    seed_action = {
        env.agent_graph.get_agent(0): ManualAction(
            action_type=ActionType.CREATE_POST,
            action_args={"content": seed_content}
        )
    }
    await env.step(seed_action)
    print(f"   Seed post created by {AGENT_NAMES.get(0, 'Agent 0')}")

    # Read initial traces (sign_ups + seed post)
    new_traces = read_new_traces(DB_PATH, trace_count)
    trace_count += len(new_traces)
    sign_ups = [t for t in new_traces if t.get("action_type") == "sign_up"]
    print(f"   {len(sign_ups)} agents registered, {len(new_traces) - len(sign_ups)} other actions")

    # Feed seed action to graph memory
    if graph_updater:
        for trace in new_traces:
            try:
                trace["info"] = json.loads(trace["info"]) if isinstance(trace["info"], str) else trace["info"]
            except (json.JSONDecodeError, TypeError):
                pass
            _enrich_trace_for_kg(trace, DB_PATH, AGENT_NAMES)
            graph_updater.add_action(trace)
        print(f"   Graph memory: +{len(new_traces)} traces")

    # ----------------------------------------------------------
    # 8. LLM-driven simulation rounds
    # ----------------------------------------------------------
    print(f"\nRunning {NUM_ROUNDS} LLM-driven simulation rounds...\n")

    def _write_progress(current, total, status="running"):
        """Write progress.json so the API can serve it."""
        if not SIM_DIR_ARG:
            return
        progress = {"current_round": current, "total_rounds": total, "status": status}
        try:
            with open(os.path.join(SIM_DIR_ARG, "progress.json"), "w") as f:
                json.dump(progress, f)
        except Exception as e:
            print(f"   WARNING: failed to write progress.json: {e}")

    def _write_actions():
        """Export all SQLite traces to actions.jsonl for the API.
        
        Enriches comment actions with post_id (not stored in OASIS trace)
        by joining the comment table via comment_id.
        """
        if not SIM_DIR_ARG:
            return
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            
            # Build comment_id -> post_id lookup
            comment_post_map = {}
            try:
                c.execute("SELECT comment_id, post_id FROM comment")
                for cid, pid in c.fetchall():
                    comment_post_map[cid] = pid
            except Exception:
                pass
            
            # Build post_id lookup: track post_ids in creation order per user
            # (trace doesn't include post_id for create_post either)
            post_ids_by_user = {}
            try:
                c.execute("SELECT post_id, user_id FROM post ORDER BY post_id")
                for pid, uid in c.fetchall():
                    if uid not in post_ids_by_user:
                        post_ids_by_user[uid] = []
                    post_ids_by_user[uid].append(pid)
            except Exception:
                pass
            
            c.execute("SELECT user_id, action, info, created_at FROM trace ORDER BY rowid")
            rows = c.fetchall()
            conn.close()
            
            # Track how many create_post traces we've seen per user
            post_counters = {}
            
            actions_path = os.path.join(SIM_DIR_ARG, "actions.jsonl")
            with open(actions_path, "w", encoding="utf-8") as f:
                for r in rows:
                    info = r[2]
                    try:
                        info = json.loads(info) if isinstance(info, str) else info
                    except (json.JSONDecodeError, TypeError):
                        pass
                    if not isinstance(info, dict):
                        info = {}
                    
                    action_type = r[1]
                    user_id = r[0]
                    
                    # Enrich create_comment with post_id
                    if action_type == "create_comment" and "post_id" not in info:
                        cid = info.get("comment_id")
                        if cid is not None and cid in comment_post_map:
                            info["post_id"] = comment_post_map[cid]
                    
                    # Enrich create_post with post_id
                    if action_type == "create_post" and "post_id" not in info:
                        uid_posts = post_ids_by_user.get(user_id, [])
                        idx = post_counters.get(user_id, 0)
                        if idx < len(uid_posts):
                            info["post_id"] = uid_posts[idx]
                        post_counters[user_id] = idx + 1
                    
                    action = {
                        "user_id": user_id,
                        "agent_name": AGENT_NAMES.get(user_id, f"agent_{user_id}"),
                        "action_type": action_type,
                        "info": info,
                        "timestamp": r[3],
                    }
                    f.write(json.dumps(action, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"   Warning: failed to write actions.jsonl: {e}")

    _write_progress(0, NUM_ROUNDS, "running")

    # Load campaign context for diverse post generation
    campaign_ctx = SIM_CONFIG.get("campaign_context", "")
    # Parse actual campaign name from context (e.g. "Campaign: Shopee Black Friday 2025\n...")
    campaign_name = SIM_CONFIG.get("campaign_id", "campaign")
    for line in campaign_ctx.split("\n"):
        if line.strip().startswith("Campaign:"):
            campaign_name = line.split(":", 1)[1].strip()
            break

    # Post topic templates to rotate through for diverse content
    _POST_TOPICS = [
        "Share your personal thoughts about {campaign}",
        "Share your impressions after experiencing {campaign}",
        "Ask everyone's opinion about {campaign}",
        "Share a fresh perspective on {campaign}",
        "Introduce {campaign} to your friends",
        "Compare {campaign} with other alternatives",
        "Share your real-world experience with {campaign}",
        "Talk about what you like or dislike about {campaign}",
    ]

    import random as _rng_module
    _rng = _rng_module.Random()  # seeded by time for variety
    from camel.messages import BaseMessage as _BM

    async def _generate_post_content(agent_model, persona: str, topic: str,
                                      memory_context: str = "") -> str:
        """Use LLM to generate a short natural social media post."""
        try:
            from camel.agents import ChatAgent
            sys_msg = _BM.make_assistant_message(
                role_name="Social Media User",
                content=(
                    "You are a social media user. Write a SHORT, natural "
                    "social media post (2-4 sentences). Write in English. "
                    "Be authentic and personal. Don't use hashtags excessively. "
                    "Don't be overly promotional."
                ),
            )
            tmp_agent = ChatAgent(system_message=sys_msg, model=agent_model)
            prompt_parts = [f"About you: {persona}"]
            if memory_context:
                prompt_parts.append(f"\n{memory_context}")
            prompt_parts.append(f"\nTopic: {topic}")
            user_msg = _BM.make_user_message(
                role_name="User",
                content="\n".join(prompt_parts),
            )
            resp = await tmp_agent.astep(user_msg)
            content = resp.msgs[0].content.strip() if resp.msgs else ""
            # Clean up -- remove quotes if LLM wrapped in quotes
            if content.startswith('"') and content.endswith('"'):
                content = content[1:-1]
            return content if len(content) > 10 else ""
        except Exception as e:
            print(f"   Warning: LLM post generation failed: {e}")
            return ""

    async def _generate_comment(agent_model, persona: str, post_content: str,
                                 memory_context: str = "") -> str:
        """Use LLM to generate a short comment -- only called for high-relevance posts."""
        try:
            from camel.agents import ChatAgent
            sys_msg = _BM.make_assistant_message(
                role_name="Commenter",
                content=(
                    "You are a social media user writing a comment. Write a SHORT, "
                    "natural comment (1-2 sentences). Be authentic. Write in English."
                ),
            )
            tmp_agent = ChatAgent(system_message=sys_msg, model=agent_model)
            comment_prompt = f"Your background: {persona[:200]}"
            if memory_context:
                comment_prompt += f"\n{memory_context}"
            comment_prompt += f"\n\nPost: {post_content[:200]}\n\nWrite a brief comment:"
            user_msg = _BM.make_user_message(
                role_name="User",
                content=comment_prompt,
            )
            resp = await tmp_agent.astep(user_msg)
            comment = resp.msgs[0].content.strip() if resp.msgs else ""
            if comment.startswith('"') and comment.endswith('"'):
                comment = comment[1:-1]
            return comment if len(comment) > 5 else ""
        except Exception as e:
            print(f"Comment generation failed: {e}")
            return ""

    # Helper: get post content from DB for comment generation
    def _get_post_content(db_path: str, post_id: int) -> str:
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT content FROM post WHERE post_id = ?", (post_id,))
            row = c.fetchone()
            conn.close()
            return row[0] if row else ""
        except Exception:
            return ""

    # ── Write initial cognitive state for tracked agent (Round 0) ──
    _tracked_id = SIM_CONFIG.get("tracked_agent_id", -1)
    if _tracked_id >= 0 and _tracked_id < len(profiles):
        _track_file = os.path.join(SIM_DIR_ARG or SCRIPT_DIR, "agent_tracking.txt")
        with open(_track_file, "w", encoding="utf-8") as tf:
            _tp = profiles[_tracked_id]
            _tn = AGENT_NAMES.get(_tracked_id, f"Agent {_tracked_id}")
            tf.write(f"AGENT COGNITIVE TRACKING LOG\n")
            tf.write(f"Agent: {_tn} (ID={_tracked_id})\n")
            tf.write(f"MBTI: {_tp.get('mbti', 'N/A')}\n")
            tf.write(f"Simulation: {NUM_ROUNDS} rounds, {len(profiles)} agents\n")
            tf.write(f"Toggles: memory={bool(agent_memory)}, mbti={bool(mbti_modifiers)}, "
                     f"drift={bool(interest_tracker)}, reflection={bool(reflection)}\n")
            tf.write(f"{'='*70}\n\n")

            tf.write(f"{'='*70}\n")
            tf.write(f"  ROUND 0 (INITIAL STATE) — {_tn}\n")
            tf.write(f"{'='*70}\n\n")

            _base = _tp.get("persona", "")
            tf.write(f"[BASE PERSONA]\n{_base}\n\n")

            # Write cognitive traits (if interest tracking enabled)
            if interest_tracker:
                _traits = interest_tracker.get_traits(_tracked_id)
                if _traits:
                    tf.write(f"[COGNITIVE TRAITS]\n")
                    tf.write(f"{_traits.describe()}\n\n")

                # Write interest vector with weights
                _items = interest_tracker.get_items(_tracked_id)
                tf.write(f"[INTEREST VECTOR] (Round 0, {len(_items)} interests)\n")
                for item in _items:
                    icon = "📌" if item["source"] == "profile" else "🔄"
                    tf.write(f"  {icon} {item['keyword']}: {item['weight']:.3f} ({item['source']})\n")
                tf.write("\n")

                # Write search queries
                _queries = interest_tracker.get_search_queries(_tracked_id, n=5)
                tf.write(f"[SEARCH QUERIES] ({len(_queries)} queries)\n")
                for i, (q, w) in enumerate(_queries):
                    tf.write(f"  q{i+1} (w={w:.2f}): \"{q}\"\n")
                tf.write("\n")
            else:
                # Fallback: simple interests from domain fields
                _gen = _tp.get("general_domain", "")
                _spec = _tp.get("specific_domain", "")
                _initial_interests = [x for x in [_spec, _gen] if x]
                tf.write(f"[INITIAL INTERESTS] ({len(_initial_interests)})\n")
                if _initial_interests:
                    tf.write(f"{', '.join(_initial_interests)}\n\n")
                else:
                    tf.write("(none)\n\n")

            _mods = mbti_modifiers.get(_tracked_id, {})
            tf.write(f"[MBTI MODIFIERS] (MBTI={_tp.get('mbti', 'N/A')})\n")
            tf.write(f"  post_mult={_mods.get('post_mult', 1.0)}, "
                     f"comment_mult={_mods.get('comment_mult', 1.0)}, "
                     f"like_mult={_mods.get('like_mult', 1.0)}, "
                     f"feed_mult={_mods.get('feed_mult', 1.0)}\n\n")

            tf.write(f"[DRIFT KEYWORDS] (0)\n(none)\n\n")
            tf.write(f"[MEMORY] (empty)\n\n[EVOLVED PERSONA] = BASE PERSONA\n")
            tf.write(f"\n{'─'*70}\n")

        print(f"[TRACKING] Tracking agent {_tn} (ID={_tracked_id}) → {_track_file}")

    for round_num in range(1, NUM_ROUNDS + 1):
        print(f"\n{'='*60}")
        print(f"  ROUND {round_num}/{NUM_ROUNDS}")
        print(f"{'='*60}")

        all_agents = list(env.agent_graph.get_agents())  # list of (id, agent)

        # =============================================
        # PRE-ROUND: REFLECTION (Phase 4)
        # =============================================
        if reflection and agent_memory:
            reflected_count = 0
            for agent_id, agent in all_agents:
                profile = profiles[agent_id] if agent_id < len(profiles) else {}
                base_persona = profile.get("persona", "")
                # Query graph for social context (Phase 5)
                _graph_ctx = ""
                if graph_helper:
                    agent_name = AGENT_NAMES.get(agent_id, f"Agent {agent_id}")
                    _graph_ctx = await graph_helper.get_social_context(agent_name)
                insight = await reflection.maybe_reflect(
                    agent_id, round_num, agent_memory, model, base_persona,
                    graph_context=_graph_ctx
                )
                if insight:
                    reflected_count += 1
                    agent_name = AGENT_NAMES.get(agent_id, f"Agent {agent_id}")
                    print(f"   [REFLECT] {agent_name}: {insight[:80]}...")
            if reflected_count > 0:
                print(f"   [Reflection] {reflected_count} agents reflected")

        # =============================================
        # PHASE 1: POST CREATION
        # =============================================
        print(f"   [Phase 1] Post creation...")

        # --- Personality-driven poster selection ---
        poster_ids = set()
        for agent_id, agent in all_agents:
            profile = profiles[agent_id] if agent_id < len(profiles) else {}
            _mods = mbti_modifiers.get(agent_id, {})
            if should_post(profile, _rng, post_mult=_mods.get("post_mult", 1.0)):
                poster_ids.add(agent_id)
        # Ensure at least 1 poster per round
        if not poster_ids:
            random_id = _rng.choice([aid for aid, _ in all_agents])
            poster_ids.add(random_id)
        # Cap posters to max 40% of agents (leave enough for interactions)
        max_posters = max(1, int(len(all_agents) * 0.4))
        if len(poster_ids) > max_posters:
            poster_ids = set(_rng.sample(list(poster_ids), max_posters))

        # --- Build Phase 1 actions: posters create, others do nothing ---
        post_actions = {}
        for agent_id, agent in all_agents:
            if agent_id in poster_ids:
                profile = profiles[agent_id] if agent_id < len(profiles) else {}
                agent_name = AGENT_NAMES.get(agent_id, f"Agent {agent_id}")
                topic_template = _POST_TOPICS[(round_num + agent_id) % len(_POST_TOPICS)]
                topic = topic_template.format(campaign=campaign_name)
                agent_persona = profile.get("persona", "")
                # Use evolved persona if reflection is active
                if reflection:
                    agent_persona = reflection.get_evolved_persona(
                        agent_id, agent_persona
                    )

                # Inject social graph context into persona (Phase 5)
                if graph_helper:
                    _social = await graph_helper.get_social_context(agent_name)
                    if _social:
                        agent_persona += f"\n\nSocial context: {_social}"

                # Memory injection (Phase 1 enhancement)
                mem_ctx = agent_memory.get_context(agent_id) if agent_memory else ""
                post_content = await _generate_post_content(
                    model, agent_persona, topic, memory_context=mem_ctx
                )
                if post_content:
                    post_actions[agent] = ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": post_content}
                    )
                    print(f"   [POST] {agent_name}: {post_content[:80]}...")
                else:
                    post_actions[agent] = ManualAction(
                        action_type=ActionType.DO_NOTHING,
                        action_args={},
                    )
            else:
                post_actions[agent] = ManualAction(
                    action_type=ActionType.DO_NOTHING,
                    action_args={},
                )

        try:
            await env.step(post_actions)
            print(f"   [Phase 1] {len(poster_ids)} posts created")
        except Exception as e:
            print(f"   ERROR in Phase 1 round {round_num}: {e}")
            _write_progress(round_num, NUM_ROUNDS, "running")
            continue

        # =============================================
        # RE-INDEX: Pick up new posts into ChromaDB
        # =============================================
        new_indexed = post_indexer.index_from_db(DB_PATH, round_num)
        print(f"   [Index] {new_indexed} new posts indexed (total: {post_indexer.count})")

        # =============================================
        # PHASE 2: INTERACTIONS (ALL agents browse & interact)
        #   Uses List[ManualAction] per agent → single env.step()
        # =============================================
        print(f"   [Phase 2] Interactions...", flush=True)

        if post_indexer.count == 0:
            print(f"   [Phase 2] No posts in ChromaDB yet, skipping interactions", flush=True)
            _write_progress(round_num, NUM_ROUNDS, "running")

            # Read traces from Phase 1
            new_traces = read_new_traces(DB_PATH, trace_count)
            trace_count += len(new_traces)
            action_summary = {}
            for trace in new_traces:
                atype = trace.get("action_type", "unknown")
                action_summary[atype] = action_summary.get(atype, 0) + 1
            if action_summary:
                print(f"   Summary: {action_summary}", flush=True)
            continue

        # --- Collect all intended actions per agent ---
        agent_action_plans = {}  # agent -> list of (type, post_id, persona)
        likes_count = 0
        comment_count = 0

        for agent_id, agent in all_agents:
            profile = profiles[agent_id] if agent_id < len(profiles) else {}
            _mods = mbti_modifiers.get(agent_id, {})

            agent_actions = decide_agent_actions(
                profile, post_indexer, DB_PATH, _rng,
                all_profiles=profiles,
                engagement_tracker=engagement_tracker,
                agent_id=agent_id,
                comment_mult=_mods.get("comment_mult", 1.0),
                like_mult=_mods.get("like_mult", 1.0),
                feed_mult=_mods.get("feed_mult", 1.0),
                drift_text=(
                    interest_tracker.get_drift_text(agent_id)
                    if interest_tracker else ""
                ),
            )

            plans = []
            for act in agent_actions:
                if act["type"] == "like_post":
                    plans.append(("like_post", act["post_id"], None))
                    likes_count += 1
                elif act["type"] == "create_comment" and act.get("needs_llm"):
                    # Store persona + memory context for comment generation
                    _base_persona = profile.get("persona", "")[:200]
                    # Use evolved persona for comments if reflection is active
                    if reflection:
                        _base_persona = reflection.get_evolved_persona(
                            agent_id, _base_persona
                        )
                    # Inject social graph context for comments (Phase 5)
                    if graph_helper:
                        _cmt_social = await graph_helper.get_social_context(
                            AGENT_NAMES.get(agent_id, f"Agent {agent_id}")
                        )
                        if _cmt_social:
                            _base_persona += f" Social: {_cmt_social[:100]}"
                    _cmt_persona = _base_persona[:300]
                    _cmt_mem = agent_memory.get_context(agent_id) if agent_memory else ""
                    plans.append(("create_comment", act["post_id"],
                                  _cmt_persona, _cmt_mem))
                    comment_count += 1

            agent_action_plans[(agent, agent_id)] = plans

        print(f"   [Phase 2] {len(all_agents)} agents: "
              f"{likes_count} likes, {comment_count} comments planned", flush=True)

        # --- Generate LLM comments upfront ---
        print(f"   Generating {comment_count} comments via LLM...", flush=True)
        # Build the final action dict: { agent -> List[ManualAction] }
        final_actions = {}
        total_comments_generated = 0

        for (agent, agent_id), plans in agent_action_plans.items():
            action_list = []

            for act_type, post_id, persona, *extra in plans:
                if act_type == "like_post":
                    action_list.append(ManualAction(
                        action_type=ActionType.LIKE_POST,
                        action_args={"post_id": post_id},
                    ))
                elif act_type == "create_comment":
                    try:
                        post_content = _get_post_content(DB_PATH, post_id)
                        mem_ctx = extra[0] if extra else ""
                        comment = await _generate_comment(
                            model, persona, post_content,
                            memory_context=mem_ctx
                        )
                    except Exception as e:
                        print(f"   WARN: comment gen failed agent {agent_id}: {e}", flush=True)
                        comment = None
                    if comment:
                        action_list.append(ManualAction(
                            action_type=ActionType.CREATE_COMMENT,
                            action_args={"post_id": post_id, "content": comment},
                        ))
                        engagement_tracker.record_comment(agent_id, post_id)
                        total_comments_generated += 1

            # Every agent must have at least one action
            if not action_list:
                action_list.append(ManualAction(
                    action_type=ActionType.DO_NOTHING,
                    action_args={},
                ))

            final_actions[agent] = action_list

        print(f"   Generated {total_comments_generated}/{comment_count} comments", flush=True)

        # --- Single env.step() with all actions ---
        print(f"   Executing all interactions in 1 env.step()...", flush=True)
        try:
            await env.step(final_actions)
            print(f"   [Phase 2] Done: {likes_count} likes + "
                  f"{total_comments_generated} comments", flush=True)
        except Exception as e:
            print(f"   ERROR in Phase 2 round {round_num}: {e}", flush=True)

        _write_progress(round_num, NUM_ROUNDS, "running")

        # Read new traces from SQLite and print to console
        new_traces = read_new_traces(DB_PATH, trace_count)
        trace_count += len(new_traces)

        # Print interactions to console
        action_summary = {}
        for trace in new_traces:
            atype = trace.get("action_type", "unknown")
            action_summary[atype] = action_summary.get(atype, 0) + 1

            # Parse info for content display
            info = trace.get("info", "")
            try:
                info = json.loads(info) if isinstance(info, str) else info
            except (json.JSONDecodeError, TypeError):
                info = {}

            agent_id = trace.get("user_id", "?")
            agent_name = AGENT_NAMES.get(agent_id, f"Agent {agent_id}")

            # Print meaningful interactions
            if atype == "create_post":
                content = info.get("content", "") if isinstance(info, dict) else str(info)
                preview = content[:120].replace("\n", " ")
                print(f"   [POST] {agent_name}: {preview}...")
            elif atype == "create_comment":
                content = info.get("content", "") if isinstance(info, dict) else str(info)
                preview = content[:100].replace("\n", " ")
                print(f"   [COMMENT] {agent_name}: {preview}...")
            elif atype == "like_post":
                print(f"   [LIKE] {agent_name} liked a post")
            elif atype == "follow":
                target = info.get("target", "?") if isinstance(info, dict) else "?"
                print(f"   [FOLLOW] {agent_name} followed {target}")
            elif atype == "repost":
                print(f"   [REPOST] {agent_name} shared a post")
            elif atype in ("sign_up", "refresh", "do_nothing"):
                pass  # skip noise
            else:
                print(f"   [{atype.upper()}] {agent_name}")

            # Update trace for graph memory
            if isinstance(info, dict):
                trace["info"] = info
            trace["round_num"] = round_num

        # Round summary
        print(f"\n   Round {round_num} summary: {len(new_traces)} actions")
        for atype, count in sorted(action_summary.items()):
            if atype not in ("sign_up", "refresh", "do_nothing"):
                print(f"     {atype}: {count}")

        # Write progress + actions after each round
        _write_progress(round_num, NUM_ROUNDS, "running")
        _write_actions()

        # Update agent memory from this round's traces
        if agent_memory:
            for trace in new_traces:
                atype = trace.get("action_type", "")
                uid = trace.get("user_id", -1)
                info = trace.get("info", {})
                preview = ""
                if isinstance(info, dict):
                    preview = info.get("content", "")[:100]
                if atype in ("create_post", "create_comment", "like_post",
                             "repost", "follow"):
                    agent_memory.record_action(uid, atype, preview)
            agent_memory.end_round(round_num)
            print(f"   Memory: {sum(agent_memory.get_round_count(i) for i in range(len(profiles)))} total round summaries")

        # Update interest vectors from this round's engagement
        if interest_tracker:
            # Collect engaged post content per agent from traces
            agent_engaged_posts = defaultdict(list)
            for trace in new_traces:
                atype = trace.get("action_type", "")
                uid = trace.get("user_id", -1)
                info = trace.get("info", {})
                if atype in ("like_post", "create_comment") and isinstance(info, dict):
                    pid = info.get("post_id")
                    if pid is not None:
                        content = _get_post_content(DB_PATH, pid)
                        if content:
                            agent_engaged_posts[uid].append(content)

            # Collect graph entities per agent (if available)
            agent_graph_entities = {}
            if graph_helper:
                for aid in range(len(profiles)):
                    aname = AGENT_NAMES.get(aid, f"Agent {aid}")
                    entities = await graph_helper.get_interest_entities(aname)
                    if entities:
                        agent_graph_entities[aid] = entities[:2]

            # Update all agents' interest vectors
            for aid in range(len(profiles)):
                contents = agent_engaged_posts.get(aid, [])
                graph_ents = agent_graph_entities.get(aid, [])
                interest_tracker.update_after_round(
                    aid, round_num, contents, graph_entities=graph_ents
                )

            total_interests = sum(interest_tracker.get_drift_count(i)
                                  for i in range(len(profiles)))
            print(f"   Interest vectors: {total_interests} total interests tracked")

        # ── Cognitive Tracking: dump tracked agent's full state ──
        _tracked_id = SIM_CONFIG.get("tracked_agent_id", -1)
        if _tracked_id >= 0 and _tracked_id < len(profiles):
            _track_file = os.path.join(
                SIM_DIR_ARG or SCRIPT_DIR, "agent_tracking.txt"
            )
            with open(_track_file, "a", encoding="utf-8") as tf:
                _tp = profiles[_tracked_id]
                _tn = AGENT_NAMES.get(_tracked_id, f"Agent {_tracked_id}")
                tf.write(f"\n{'='*70}\n")
                tf.write(f"  ROUND {round_num}/{NUM_ROUNDS} — Tracked Agent: {_tn} (ID={_tracked_id})\n")
                tf.write(f"{'='*70}\n\n")

                # Base persona
                _base = _tp.get("persona", "")
                tf.write(f"[BASE PERSONA]\n{_base}\n\n")

                # Evolved persona
                if reflection:
                    _evolved = reflection.get_evolved_persona(_tracked_id, _base)
                    tf.write(f"[EVOLVED PERSONA] ({reflection.get_insight_count(_tracked_id)} insights)\n{_evolved}\n\n")

                # Memory
                if agent_memory:
                    _mem = agent_memory.get_context(_tracked_id)
                    tf.write(f"[MEMORY] ({agent_memory.get_round_count(_tracked_id)} rounds)\n")
                    tf.write(f"{_mem if _mem else '(empty)'}\n\n")

                # Interest vector (weighted interests)
                if interest_tracker:
                    _items = interest_tracker.get_items(_tracked_id)
                    tf.write(f"[INTEREST VECTOR] (Round {round_num}, {len(_items)} interests)\n")
                    for item in _items:
                        icon = "📌" if item["source"] == "profile" else "🔄"
                        trend = " ↑" if item["engagement_count"] > 0 else ""
                        new = " NEW" if item["first_seen"] == round_num else ""
                        tf.write(f"  {icon} {item['keyword']}: {item['weight']:.3f} "
                                 f"({item['source']}, engaged {item['engagement_count']}x)"
                                 f"{trend}{new}\n")
                    tf.write("\n")

                    # Search queries used this round
                    _queries = interest_tracker.get_search_queries(_tracked_id, n=5)
                    tf.write(f"[SEARCH QUERIES] ({len(_queries)} queries)\n")
                    for i, (q, w) in enumerate(_queries):
                        tf.write(f"  q{i+1} (w={w:.2f}): \"{q}\"\n")
                    tf.write("\n")
                else:
                    tf.write(f"[DRIFT KEYWORDS] (0)\n(none)\n\n")

                # MBTI modifiers
                _mods = mbti_modifiers.get(_tracked_id, {})
                tf.write(f"[MBTI MODIFIERS] (MBTI={_tp.get('mbti', 'N/A')})\n")
                tf.write(f"  post_mult={_mods.get('post_mult', 1.0)}, "
                         f"comment_mult={_mods.get('comment_mult', 1.0)}, "
                         f"like_mult={_mods.get('like_mult', 1.0)}, "
                         f"feed_mult={_mods.get('feed_mult', 1.0)}\n\n")

                # Graph social context (Phase 5)
                if graph_helper:
                    import asyncio
                    _tn_name = AGENT_NAMES.get(_tracked_id, f"Agent {_tracked_id}")
                    try:
                        _gctx = await graph_helper.get_social_context(_tn_name)
                        tf.write(f"[GRAPH SOCIAL CONTEXT]\n")
                        tf.write(f"{_gctx if _gctx else '(no graph data)'}\n\n")
                    except Exception:
                        tf.write(f"[GRAPH SOCIAL CONTEXT]\n(query failed)\n\n")
                else:
                    tf.write(f"[GRAPH SOCIAL CONTEXT]\n(disabled)\n\n")

                # Actions this round
                tf.write(f"[ACTIONS THIS ROUND]\n")
                _round_actions = [
                    t for t in new_traces
                    if t.get("user_id") == _tracked_id
                    and t.get("action_type") not in ("sign_up", "refresh", "do_nothing")
                ]
                if _round_actions:
                    for t in _round_actions:
                        _at = t.get("action_type", "?")
                        _info = t.get("info", {})
                        try:
                            _info = json.loads(_info) if isinstance(_info, str) else _info
                        except:
                            _info = {}
                        _content = _info.get("content", "")[:150] if isinstance(_info, dict) else ""
                        tf.write(f"  {_at}: {_content}\n")
                else:
                    tf.write(f"  (no actions)\n")
                tf.write(f"\n{'─'*70}\n")

            if round_num == 1:
                print(f"   [TRACKING] Agent tracking → {_track_file}")

        # Feed to graph memory (enriched with post context)
        if graph_updater:
            for trace in new_traces:
                _enrich_trace_for_kg(trace, DB_PATH, AGENT_NAMES)
                graph_updater.add_action(trace)
            print(f"   Graph memory: +{len(new_traces)} traces")

    # Final progress
    _write_progress(NUM_ROUNDS, NUM_ROUNDS, "completed")
    _write_actions()
    print(f"\nAll {NUM_ROUNDS} rounds completed. Total traces: {trace_count}")

    # ----------------------------------------------------------
    # 9. Stop graph memory & close simulation
    # ----------------------------------------------------------
    if graph_updater:
        print("\n[FLUSH] Flushing graph memory (waiting for pending writes)...")
        graph_updater.stop(flush=True)
        print(f"   [OK] Graph memory stopped -- {graph_updater._total_episodes} episodes written")

    # Close graph cognitive helper
    if graph_helper:
        import asyncio
        try:
            await graph_helper.close()
            print("   [OK] Graph cognitive helper closed")
        except Exception:
            pass

    print("\n[END] Closing simulation...")
    await env.close()

    print(f"\n{'='*60}")
    print(f"=== SIMULATION COMPLETE ===")
    print(f"   Database: {os.path.abspath(DB_PATH)}")
    print(f"   Agents: {len(profiles)}")
    print(f"   Rounds: {NUM_ROUNDS}")
    if graph_updater:
        print(f"   Graph Episodes: {graph_updater._total_episodes}")
        print(f"   Simulation ID: {sim_id}")
        print(f"   FalkorDB: falkor://{FALKOR_HOST}:{FALKOR_PORT}")
    print(f"   Graph Cognition: {'ENABLED' if graph_helper else 'disabled'}")
    print(f"{'='*60}")
    print(f"\n[ANALYZE] To analyze results:")
    print(f"   SQLite:   SELECT * FROM trace ORDER BY created_at;")
    if graph_updater:
        print(f"   FalkorDB: graphiti.search('Shopee Black Friday', group_ids=['{sim_id}'])")


if __name__ == "__main__":
    asyncio.run(main())


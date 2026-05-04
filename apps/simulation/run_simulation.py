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
from typing import Any, Dict, List, Optional

# Fix Windows console encoding for Vietnamese text
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ==============================================================
# 1. Bootstrap shared library + Load .env config
# ==============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
def _find_repo_root(start):
    import pathlib as _pl
    here = _pl.Path(start).resolve()
    for parent in [here, *here.parents]:
        if (parent / "libs" / "ecosim-common" / "src").is_dir():
            return str(parent)
    return os.path.dirname(start)
ECOSIM_ROOT = _find_repo_root(SCRIPT_DIR)
ENV_PATH = os.path.join(ECOSIM_ROOT, ".env")

# Add libs/ecosim-common/src để import ecosim_common
_SHARED = os.path.join(ECOSIM_ROOT, "libs", "ecosim-common", "src")
if os.path.isdir(_SHARED) and _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

# Add vendored/oasis để import oasis (upstream camel-oasis subpackage)
_VENDORED_OASIS = os.path.join(ECOSIM_ROOT, "vendored", "oasis")
if os.path.isdir(_VENDORED_OASIS) and _VENDORED_OASIS not in sys.path:
    sys.path.insert(0, _VENDORED_OASIS)

from ecosim_common.atomic_io import atomic_write_json, atomic_write_text, atomic_append_jsonl

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
    # Phase 10 rename: file đổi tên thành `config.json`. Legacy `simulation_config.json`
    # giữ làm fallback cho sims cũ.
    config_path = None
    for _candidate in ("config.json", "simulation_config.json"):
        _p = os.path.join(SIM_DIR_ARG, _candidate)
        if os.path.exists(_p):
            config_path = _p
            break
    if config_path:
        with open(config_path, "r", encoding="utf-8") as f:
            SIM_CONFIG = json.load(f)
        NUM_ROUNDS = SIM_CONFIG.get("num_rounds", 3)
        print(f"   Loaded config from {config_path} (rounds={NUM_ROUNDS})")
    else:
        print(f"   WARN: no config.json or simulation_config.json found in {SIM_DIR_ARG}")

# Hours simulated per round (Tier B fix): simulation_hours / num_rounds
# Fallback 24 (1 round = 1 ngày) nếu config không có time_config.
_time_config = SIM_CONFIG.get("time_config", {}) if isinstance(SIM_CONFIG.get("time_config", {}), dict) else {}
_sim_hours = _time_config.get("simulation_hours") or SIM_CONFIG.get("simulation_hours") or 168
HOURS_PER_ROUND = max(0.25, float(_sim_hours) / max(1, NUM_ROUNDS))
PERIOD_MULTIPLIERS = _time_config.get("period_multipliers") or SIM_CONFIG.get("period_multipliers") or {}

def _period_mult_for_round(round_num: int) -> float:
    """Lookup period_multiplier cho hour hiện tại của round.

    Bucket key format ``"HH-HH"`` (ví dụ ``"18-22"``). Nếu không có bucket khớp
    ⇒ return 1.0 (không áp dụng). Tier B — H3 fix.
    """
    if not PERIOD_MULTIPLIERS:
        return 1.0
    current_hour = int((round_num * HOURS_PER_ROUND) % 24)
    for bucket, mult in PERIOD_MULTIPLIERS.items():
        try:
            lo_s, hi_s = bucket.split("-")
            lo, hi = int(lo_s), int(hi_s)
        except Exception:
            continue
        if lo <= hi:
            hit = lo <= current_hour < hi
        else:  # wrap midnight, e.g. "22-00" → 22-24
            hit = current_hour >= lo or current_hour < hi
        if hit:
            try:
                return float(mult)
            except (TypeError, ValueError):
                return 1.0
    return 1.0

# Profile path: prefer sim_dir/profiles.json, then backend default
if SIM_DIR_ARG and os.path.exists(os.path.join(SIM_DIR_ARG, "profiles.json")):
    PROFILE_PATH = os.path.join(SIM_DIR_ARG, "profiles.json")
else:
    PROFILE_PATH = os.path.join(ECOSIM_ROOT, "apps", "core", "test_output", "test_profiles.json")

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
# Phase 11: agent profile cache (mbti, role) cho Zep JSON structured episodes
AGENT_PROFILES = {
    i: {
        "mbti": p.get("mbti", "") or "",
        "role": p.get("role", "") or p.get("entity_type", "") or "",
    }
    for i, p in enumerate(profiles)
}

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


def _enrich_traces_for_kg_batch(traces: list, db_path: str, agent_names: dict) -> None:
    """Phase 12 #3: Bulk-fetch post/comment context cho tất cả traces trong 1 round.

    Trước fix (N+1): mỗi trace mở 1 SQLite connection + 1-2 SELECT → 200 traces ×
    1ms overhead = 200ms-1s/round chỉ để open/close connections + queries.

    Sau fix: 1 connection + 2 IN-clause queries cho toàn batch:
      • Resolve all comment_id → post_id 1 query
      • Fetch all post {content, user_id} 1 query
      • Annotate traces in-place

    Compatible signatures:
      • action_type='like_post' / 'dislike_post': info có post_id → fill post_content + author
      • action_type='create_comment': info có comment_id (hoặc post_id) → resolve → fill
    """
    if not traces:
        return

    # Step 1: parse info JSON inline (mutate trace)
    parsed_traces = []
    needed_post_ids: set = set()
    needed_comment_ids: set = set()

    for trace in traces:
        info = trace.get("info", {})
        if isinstance(info, str):
            try:
                info = json.loads(info)
                trace["info"] = info
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(info, dict):
            continue

        atype = trace.get("action_type", "")
        if atype in ("like_post", "dislike_post"):
            pid = info.get("post_id")
            if pid is not None:
                needed_post_ids.add(int(pid))
                parsed_traces.append((trace, info, atype, pid, None))
        elif atype == "create_comment":
            pid = info.get("post_id")
            cid = info.get("comment_id")
            if pid is None and cid is not None:
                needed_comment_ids.add(int(cid))
                parsed_traces.append((trace, info, atype, None, cid))
            elif pid is not None:
                needed_post_ids.add(int(pid))
                parsed_traces.append((trace, info, atype, pid, None))

    if not parsed_traces:
        return

    # Step 2: bulk SQLite lookup — 1 connection, 2 queries
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # Resolve comment_id → post_id (chỉ create_comment thiếu post_id)
        comment_to_post: dict = {}
        if needed_comment_ids:
            ph = ",".join("?" * len(needed_comment_ids))
            c.execute(
                f"SELECT comment_id, post_id FROM comment WHERE comment_id IN ({ph})",
                tuple(needed_comment_ids),
            )
            for cid, pid in c.fetchall():
                comment_to_post[int(cid)] = int(pid)
                needed_post_ids.add(int(pid))

        # Bulk fetch post content + author cho all post_ids
        post_data: dict = {}  # post_id → (content, user_id)
        if needed_post_ids:
            ph = ",".join("?" * len(needed_post_ids))
            c.execute(
                f"SELECT post_id, content, user_id FROM post WHERE post_id IN ({ph})",
                tuple(needed_post_ids),
            )
            for pid, content, user_id in c.fetchall():
                post_data[int(pid)] = (content or "", user_id)

        conn.close()
    except Exception as e:
        logging.getLogger("ecosim").debug("Bulk trace enrichment error: %s", e)
        return

    # Step 3: annotate traces in-place
    for trace, info, atype, pid, cid in parsed_traces:
        if pid is None and cid is not None:
            pid = comment_to_post.get(int(cid))
            if pid is not None:
                info["post_id"] = pid
        if pid is None:
            continue
        row = post_data.get(int(pid))
        if not row:
            continue
        content, author_uid = row
        info["post_content"] = content[:500]
        info["post_author_id"] = author_uid
        info["post_author_name"] = agent_names.get(author_uid, f"Agent {author_uid}")


def _enrich_trace_for_kg(trace: dict, db_path: str, agent_names: dict):
    """Backward-compat single-trace wrapper. Prefer _enrich_traces_for_kg_batch."""
    _enrich_traces_for_kg_batch([trace], db_path, agent_names)


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
    # 5. Phase 15 — Zep section dispatch setup
    # ----------------------------------------------------------
    # sim_id giữ làm logical id; graph_name là FalkorDB graph name (= sim graph
    # đã fork từ master). Ưu tiên `kg_graph_name` từ SIM_CONFIG (set bởi
    # /api/sim/prepare). Fallback build từ sim_args.group_id để không break
    # legacy callers chạy `run_simulation.py` standalone với --group-id flag.
    sim_id = sim_args.group_id or f"ecosim_{uuid.uuid4().hex[:8]}"
    graph_name = SIM_CONFIG.get("kg_graph_name") or (
        sim_id if sim_id.startswith("sim_") else f"sim_{sim_id}"
    )

    # Phase 15: end-of-round Zep section dispatch (sync). Replace runtime
    # FalkorGraphMemoryUpdater queue path. Each round → write_round_sections_via_zep
    # (Node 1-10). Sim COMPLETED → finalize_sim_post_run (Node 11-12).
    zep_section_enabled = (
        ENABLE_GRAPH
        and os.getenv("ZEP_API_KEY")
        and os.getenv("ZEP_SIM_RUNTIME", "true").lower() == "true"
    )
    zep_llm_client = None
    if zep_section_enabled:
        try:
            from ecosim_common.llm_client import LLMClient as _LLMClient
            zep_llm_client = _LLMClient()
            print(f"[BRAIN] Zep section dispatch ENABLED (graph={graph_name})")
            print(f"   FalkorDB: falkor://{FALKOR_HOST}:{FALKOR_PORT}")
        except Exception as e:
            print(f"[WARN]  Zep section dispatch init failed: {e}")
            zep_section_enabled = False
    else:
        print("[INFO]  Zep section dispatch disabled (need ENABLE_GRAPH_MEMORY=true + ZEP_API_KEY)")

    # ----------------------------------------------------------
    # 5b. Graph Cognitive Helper (reads from FalkorDB sim graph)
    # ----------------------------------------------------------
    # Yêu cầu duy nhất: FalkorDB up. Sim graph có master clone (Layer 1) +
    # seeded SimAgent + Phase 15 Zep extract sau round 1+ → query semantic
    # context từ round 1 trở đi. Round 0 sẽ empty (chưa có content actions).
    graph_helper = None
    if SIM_CONFIG.get("enable_graph_cognition", False) and ENABLE_GRAPH:
        try:
            from agent_cognition import GraphCognitiveHelper
            graph_helper = GraphCognitiveHelper(
                falkor_host=FALKOR_HOST,
                falkor_port=FALKOR_PORT,
                group_id=graph_name,
            )
            print("[COGNITION] Graph Cognition ENABLED (reads FalkorDB sim graph)")
        except Exception as e:
            print(f"[WARN] Graph Cognition init failed: {e}")
            graph_helper = None
    elif SIM_CONFIG.get("enable_graph_cognition", False):
        print("[WARN] Graph Cognition requested but ENABLE_GRAPH_MEMORY=false — skipped")

    # ----------------------------------------------------------
    # 5c. Crisis Injection Engine
    # ----------------------------------------------------------
    crisis_engine = None
    crisis_events_config = SIM_CONFIG.get("crisis_events", [])
    if crisis_events_config:
        from crisis_engine import CrisisEngine, CrisisEvent
        events = [CrisisEvent.from_dict(e) for e in crisis_events_config]
        crisis_engine = CrisisEngine(events)
        print(f"[CRISIS] Engine ENABLED ({len(events)} scheduled events)")
        for ev in events:
            print(f"   Round {ev.trigger_round}: {ev.title} ({ev.crisis_type}, severity={ev.severity})")
    else:
        # Still init engine for real-time injection support
        from crisis_engine import CrisisEngine, CrisisEvent
        crisis_engine = CrisisEngine()
        print("[CRISIS] Engine ready (no scheduled events, real-time injection available)")

    # ----------------------------------------------------------
    # 6. Reset (start platform + sign up agents)
    # ----------------------------------------------------------
    # Initialize interest-based feed recommendation (Tier B: per-sim + persistent)
    # Collection name dùng graph_name để consistent với KG (cùng "sim_<id>" prefix).
    # Phase 7.1: PostIndexer chroma → `<sim>/posts/chroma/` (sim mới). Sim cũ
    # legacy `<sim>/chroma/`: nếu tồn tại thì migrate dùng tiếp, else dùng path mới.
    if SIM_DIR_ARG:
        _legacy_chroma = os.path.join(SIM_DIR_ARG, "chroma")
        _new_chroma = os.path.join(SIM_DIR_ARG, "posts", "chroma")
        if os.path.isdir(_legacy_chroma) and not os.path.isdir(_new_chroma):
            _chroma_dir = _legacy_chroma  # backward compat sim cũ
        else:
            os.makedirs(os.path.dirname(_new_chroma), exist_ok=True)
            _chroma_dir = _new_chroma
    else:
        _chroma_dir = None
    post_indexer = PostIndexer(
        sim_id=graph_name,
        persist_dir=_chroma_dir,
    )
    engagement_tracker = EngagementTracker()
    print(
        f"[STATS] Interest-based feed initialized (collection={post_indexer._collection_name}, "
        f"persist={bool(_chroma_dir)})"
    )

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

    # ── Phase 3.1: Init ecosim_agent_memory FalkorDB graph khi
    # enable_graph_cognition=true. Persist FIFO summaries + reflection insights
    # vào graph riêng cho post-sim queries (Interview/Report).
    agent_mem_graph_active = False
    if SIM_CONFIG.get("enable_graph_cognition", False):
        try:
            from agent_memory_graph import ensure_agent_memory_graph
            agent_mem_graph_active = ensure_agent_memory_graph(
                falkor_host=FALKOR_HOST, falkor_port=FALKOR_PORT,
            )
            if agent_mem_graph_active:
                print("[COGNITION] Agent memory graph ensured (ecosim_agent_memory)")
            else:
                print("[COGNITION] Agent memory graph init failed — skipping persistence")
        except Exception as e:
            print(f"[WARN] agent_memory_graph init exception: {e}")

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

    # Reset actions.jsonl nếu DB fresh (atomic append không tự clear)
    if SIM_DIR_ARG:
        _actions_path = os.path.join(SIM_DIR_ARG, "actions.jsonl")
        try:
            if os.path.exists(_actions_path):
                os.remove(_actions_path)
        except OSError:
            pass

    # Seed post author — cấu hình qua simulation_config.crisis_author_strategy
    # (Tier B H6/M7): "agent_0" (default), "influencer", "system"
    _seed_strategy = SIM_CONFIG.get("seed_author_strategy") or SIM_CONFIG.get("crisis_author_strategy") or "agent_0"
    from crisis_engine import CrisisEngine as _CE
    _seed_author_id = _CE.resolve_author_id(_seed_strategy, profiles)

    print(f"\n{'='*60}")
    print(f"  SEED POST (Campaign Injection — strategy={_seed_strategy}, author={_seed_author_id})")
    print(f"{'='*60}")
    seed_preview = seed_content[:200].replace("\n", " ")
    print(f"   Content: {seed_preview}...")
    seed_action = {
        env.agent_graph.get_agent(_seed_author_id): ManualAction(
            action_type=ActionType.CREATE_POST,
            action_args={"content": seed_content}
        )
    }
    await env.step(seed_action)
    print(f"   Seed post created by {AGENT_NAMES.get(_seed_author_id, f'Agent {_seed_author_id}')}")

    # Read initial traces (sign_ups + seed post)
    new_traces = read_new_traces(DB_PATH, trace_count)
    trace_count += len(new_traces)
    sign_ups = [t for t in new_traces if t.get("action_type") == "sign_up"]
    print(f"   {len(sign_ups)} agents registered, {len(new_traces) - len(sign_ups)} other actions")

    # Phase 15: enrich traces (parse info JSON + fetch parent post for comments).
    # Seed action chỉ có sign_ups + 1 seed post → write_round_sections_via_zep
    # filter ra create_post duy nhất (round_num=0) → submit Zep nếu enabled.
    if zep_section_enabled:
        _enrich_traces_for_kg_batch(new_traces, DB_PATH, AGENT_NAMES)
        try:
            from sim_zep_section_writer import write_round_sections_via_zep
            _seed_stats = await write_round_sections_via_zep(
                round_num=0, traces=new_traces,
                agent_names=AGENT_NAMES, agent_profiles=AGENT_PROFILES,
                sim_id=graph_name, llm=zep_llm_client,
                falkor_host=FALKOR_HOST, falkor_port=FALKOR_PORT,
            )
            print(f"   Zep seed dispatch: {_seed_stats.get('status')} "
                  f"(sections={_seed_stats.get('sections_submitted', 0)})")
        except Exception as _e:
            print(f"   [WARN] Zep seed dispatch failed: {_e}")

    # ----------------------------------------------------------
    # 8. LLM-driven simulation rounds
    # ----------------------------------------------------------
    print(f"\nRunning {NUM_ROUNDS} LLM-driven simulation rounds...\n")

    def _write_progress(current, total, status="running"):
        """Write progress.json so the API can serve it (atomic)."""
        if not SIM_DIR_ARG:
            return
        progress = {"current_round": current, "total_rounds": total, "status": status}
        try:
            atomic_write_json(os.path.join(SIM_DIR_ARG, "progress.json"), progress)
        except Exception as e:
            print(f"   WARNING: failed to write progress.json: {e}")

    # actions.jsonl append offset (Tier B C4: chuyển full-rewrite → atomic append)
    _actions_offset = {"value": 0}

    def _write_actions():
        """Append NEW SQLite traces into actions.jsonl atomically.

        Tier B — C4 fix: thay vì đọc toàn bộ trace + ghi đè file (risk mất data
        nếu crash giữa write), giờ chỉ append các trace mới (track offset qua
        `_actions_offset`) dùng `atomic_append_jsonl` — mỗi line là 1 atomic write.
        """
        if not SIM_DIR_ARG:
            return
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # Build comment_id -> post_id lookup (cần cho enrich create_comment)
            comment_post_map = {}
            try:
                c.execute("SELECT comment_id, post_id FROM comment")
                for cid, pid in c.fetchall():
                    comment_post_map[cid] = pid
            except Exception:
                pass

            # Build post_id lookup per user cho enrich create_post
            post_ids_by_user = {}
            try:
                c.execute("SELECT post_id, user_id FROM post ORDER BY post_id")
                for pid, uid in c.fetchall():
                    post_ids_by_user.setdefault(uid, []).append(pid)
            except Exception:
                pass

            offset = _actions_offset["value"]
            c.execute(
                "SELECT user_id, action, info, created_at FROM trace "
                "ORDER BY rowid LIMIT -1 OFFSET ?",
                (offset,),
            )
            rows = c.fetchall()
            conn.close()

            # post_counter per user cần tái xây dựng từ đầu để giữ chỉ số nhất quán
            # với các trace đã append ở lần trước — nhưng vì chúng ta chỉ xử lý
            # trace mới nên counter offset được lưu trong state.
            post_counters = _actions_offset.setdefault("post_counters", {})

            actions_path = os.path.join(SIM_DIR_ARG, "actions.jsonl")
            appended = 0
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

                if action_type == "create_comment" and "post_id" not in info:
                    cid = info.get("comment_id")
                    if cid is not None and cid in comment_post_map:
                        info["post_id"] = comment_post_map[cid]

                if action_type == "create_post" and "post_id" not in info:
                    uid_posts = post_ids_by_user.get(user_id, [])
                    idx = post_counters.get(user_id, 0)
                    if idx < len(uid_posts):
                        info["post_id"] = uid_posts[idx]
                    post_counters[user_id] = idx + 1

                record = {
                    "user_id": user_id,
                    "agent_name": AGENT_NAMES.get(user_id, f"agent_{user_id}"),
                    "action_type": action_type,
                    "info": info,
                    "timestamp": r[3],
                }
                atomic_append_jsonl(actions_path, record)
                appended += 1

            _actions_offset["value"] = offset + appended
        except Exception as e:
            print(f"   Warning: failed to append actions.jsonl: {e}")

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

    # Extra context pulled from event/time config (Tier B enrichment)
    _event_config = SIM_CONFIG.get("event_config", {}) if isinstance(SIM_CONFIG.get("event_config", {}), dict) else {}
    HOT_TOPICS = _event_config.get("hot_topics") or []
    NARRATIVE_DIRECTION = _event_config.get("narrative_direction", "").strip()

    async def _generate_post_content(
        agent_model,
        persona: str,
        topic: str,
        memory_context: str = "",
        interest_keywords: Optional[List[str]] = None,
        crisis_directive: str = "",
        crisis_intensity: str = "context_only",
    ) -> str:
        """Use LLM to generate a short natural social media post.

        Crisis injection: when `crisis_directive` is non-empty, it is placed
        at the LAST line of the prompt (LLM follows the last instruction
        most strongly). When `crisis_intensity == "strong"`, the directive
        replaces the campaign topic entirely so the agent is steered toward
        the active event instead of the default Black Friday brief.
        """
        try:
            from camel.agents import ChatAgent
            sys_msg = _BM.make_assistant_message(
                role_name="Social Media User",
                content=(
                    "You are a social media user. Write a SHORT, natural "
                    "social media post (2-4 sentences). Write in English. "
                    "Be authentic and personal. Don't use hashtags excessively. "
                    "Don't be overly promotional. Do not wrap the post in quotes."
                ),
            )
            # Control temperature + max_tokens (Tier B H2 fix)
            _cfg = dict(getattr(agent_model, "model_config_dict", {}) or {})
            _cfg.setdefault("temperature", 0.8)
            _cfg.setdefault("max_tokens", 220)
            try:
                agent_model.model_config_dict = _cfg
            except Exception:
                pass
            tmp_agent = ChatAgent(system_message=sys_msg, model=agent_model)

            prompt_parts = [f"About you: {persona}"]
            if memory_context:
                prompt_parts.append(memory_context)
            if interest_keywords:
                kws = ", ".join(interest_keywords[:5])
                prompt_parts.append(f"Your current top interests: {kws}")
            if HOT_TOPICS:
                prompt_parts.append(f"Trending topics right now: {', '.join(HOT_TOPICS[:5])}")
            if NARRATIVE_DIRECTION:
                prompt_parts.append(f"Conversation direction: {NARRATIVE_DIRECTION}")

            # Strong crisis: directive REPLACES the default campaign topic so
            # the LLM is fully steered toward the event. Soft: keep topic and
            # append directive after it. Context-only: no directive line.
            if crisis_intensity == "strong" and crisis_directive:
                prompt_parts.append(crisis_directive)
            else:
                prompt_parts.append(f"Topic: {topic}")
                if crisis_directive:
                    prompt_parts.append(crisis_directive)

            user_msg = _BM.make_user_message(
                role_name="User",
                content="\n\n".join(prompt_parts),
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

    async def _generate_comment(
        agent_model,
        persona: str,
        post_content: str,
        memory_context: str = "",
        interest_keywords: Optional[List[str]] = None,
        crisis_directive: str = "",
        crisis_intensity: str = "context_only",
    ) -> str:
        """Use LLM to generate a short comment -- only called for high-relevance posts.

        Crisis injection: persona cap raised to 600 chars so the appended
        BREAKING NEWS block survives. When `crisis_directive` is non-empty,
        the post being commented on is shown in full (up to 600 chars) and
        an imperative line is appended just before the final "Write a brief
        comment..." instruction so the LLM doesn't default to bland filler.
        """
        try:
            from camel.agents import ChatAgent
            sys_msg = _BM.make_assistant_message(
                role_name="Commenter",
                content=(
                    "You are a social media user writing a comment. Write a SHORT, "
                    "natural comment (1-2 sentences). Be authentic. Write in English. "
                    "Do not wrap the comment in quotes."
                ),
            )
            # Control temperature + max_tokens (Tier B H2 fix)
            _cfg = dict(getattr(agent_model, "model_config_dict", {}) or {})
            _cfg.setdefault("temperature", 0.8)
            _cfg.setdefault("max_tokens", 150)
            try:
                agent_model.model_config_dict = _cfg
            except Exception:
                pass
            tmp_agent = ChatAgent(system_message=sys_msg, model=agent_model)

            # Persona cap raised 300→600: persona has BREAKING NEWS appended
            # at the end, and the previous 300-char cap was stripping it.
            # Post cap raised 250→600 when a crisis is active so the full
            # crisis post (~440 chars in observed sims) is visible.
            _post_cap = 600 if crisis_directive else 250
            parts = [f"Your background: {persona[:600]}"]
            if memory_context:
                parts.append(memory_context)
            if interest_keywords:
                parts.append(f"Your top interests: {', '.join(interest_keywords[:5])}")
            parts.append(f"Post: {post_content[:_post_cap]}")
            if crisis_directive:
                parts.append(crisis_directive)
            if crisis_directive and crisis_intensity == "strong":
                parts.append(
                    "Write a brief comment (1-2 sentences) that explicitly "
                    "addresses the active event above:"
                )
            elif crisis_directive:
                parts.append(
                    "Write a brief comment (1-2 sentences) that may touch on "
                    "the active event if it fits:"
                )
            else:
                parts.append("Write a brief comment (1-2 sentences):")

            user_msg = _BM.make_user_message(
                role_name="User",
                content="\n\n".join(parts),
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

    # ── Phase 15.tracking: init JSONL tracking + write Round 0 cho list of agents ──
    _tracked_ids = SIM_CONFIG.get("tracked_agent_ids") or []
    if not _tracked_ids:
        # Backward compat — legacy single field
        _legacy = SIM_CONFIG.get("tracked_agent_id", -1)
        if _legacy >= 0:
            _tracked_ids = [_legacy]
    # Filter valid
    _tracked_ids_raw = list(_tracked_ids)
    _tracked_ids = [i for i in _tracked_ids if 0 <= i < len(profiles)]
    print(
        f"   [TRACKING-DIAG] config.tracked_agent_ids={SIM_CONFIG.get('tracked_agent_ids')} "
        f"raw={_tracked_ids_raw} valid={_tracked_ids} "
        f"len(profiles)={len(profiles)} SIM_DIR_ARG={SIM_DIR_ARG!r}"
    )

    if _tracked_ids and SIM_DIR_ARG:
        try:
            from agent_tracking_writer import init_tracking, write_agent_round
            init_tracking(SIM_DIR_ARG)
            print(f"   [TRACKING] init_tracking() done, writing Round 0 records...")
            for _tid in _tracked_ids:
                _tp0 = profiles[_tid]
                _ct0 = {}
                _iv0 = []
                _sq0 = []
                if interest_tracker:
                    _t = interest_tracker.get_traits(_tid)
                    if _t:
                        _ct0 = _t.to_dict()
                    _iv0 = [
                        {**it, "trending": False, "is_new": False}
                        for it in interest_tracker.get_items(_tid)
                    ]
                    _sq0 = [
                        {"weight": w, "query": q}
                        for q, w in interest_tracker.get_search_queries(_tid, n=5)
                    ]
                # Query Graph Cognitive Helper — at Round 0 the sim graph
                # is freshly forked from master so it has campaign entities
                # but no agent activity history yet. Some context still
                # available (campaign brand entities). Best-effort: empty
                # on failure or disabled.
                _gctx0 = ""
                if graph_helper:
                    try:
                        _gctx0 = await graph_helper.get_social_context(
                            AGENT_NAMES.get(_tid, f"Agent {_tid}")
                        )
                    except Exception:
                        _gctx0 = ""
                write_agent_round(
                    SIM_DIR_ARG,
                    round_num=0,
                    agent_id=_tid,
                    agent_name=AGENT_NAMES.get(_tid, f"Agent {_tid}"),
                    mbti=_tp0.get("mbti", ""),
                    base_persona=_tp0.get("persona", ""),
                    evolved_persona=_tp0.get("persona", ""),
                    cognitive_traits=_ct0,
                    interest_vector=_iv0,
                    search_queries=_sq0,
                    mbti_modifiers=mbti_modifiers.get(_tid, {}),
                    memory="",
                    graph_context=_gctx0,
                    actions=[],
                )
            print(f"   [TRACKING] init Round 0 cho {len(_tracked_ids)} agents: {_tracked_ids}")
        except Exception as _je:
            print(f"   WARN: JSONL tracking init fail: {_je}")
    # Backward-compat alias cho rest of file
    _tracked_id = _tracked_ids[0] if _tracked_ids else -1

    # Legacy text format writer (giữ cho backward compat)
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
        # CRISIS INJECTION CHECK (scheduled + real-time)
        #
        # Crisis is one-shot: fires only at `trigger_round`. Persistence is
        # carried by each agent's interest vector (keywords decay/boost via
        # `update_after_round` based on per-agent traits + engagement).
        # =============================================
        events_this_round: List[Any] = []
        if crisis_engine:
            # 1. Check for real-time injections from API (file IPC)
            if SIM_DIR_ARG:
                new_rt = crisis_engine.load_pending_events(SIM_DIR_ARG, round_num)
                if new_rt:
                    print(f"   🚨 [CRISIS] {len(new_rt)} real-time event(s) loaded from API")

            # 2. Get events firing this round (one-shot — no persist window)
            events_this_round = crisis_engine.get_events_for_round(round_num)

            for crisis in events_this_round:
                print(
                    f"   🚨 [CRISIS] INJECTING: {crisis.title} "
                    f"(type={crisis.crisis_type}, severity={crisis.severity})"
                )

                # A. Generate and inject breaking news post
                crisis_post = await crisis_engine.generate_crisis_post(crisis, model)
                _cstrategy = SIM_CONFIG.get("crisis_author_strategy", "agent_0")
                _cauthor_id = crisis_engine.resolve_author_id(_cstrategy, profiles)
                crisis_action = {
                    env.agent_graph.get_agent(_cauthor_id): ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": crisis_post}
                    )
                }
                await env.step(crisis_action)
                print(f"   📰 [CRISIS POST by {AGENT_NAMES.get(_cauthor_id, _cauthor_id)}] {crisis_post[:100]}...")

                # B. Re-index the crisis post into ChromaDB immediately
                post_indexer.index_from_db(DB_PATH, round_num)

                # C. 2-stage LLM keyword pipeline:
                #    (1) extract a wide pool of 2*N candidates from crisis
                #        title/description.
                #    (2) "impact analyst" LLM selects the N most relevant to
                #        the current campaign (name + market + summary).
                # Then inject the N selected into every agent's interest
                # vector with weight = severity (flat). Persistence is
                # owned by InterestVectorTracker.update_after_round.
                if interest_tracker:
                    n_target = crisis.n_keywords
                    n_extract = min(20, n_target * 2)  # wider pool, capped
                    candidate_keywords = await crisis_engine.extract_keywords(
                        crisis, model, n=n_extract
                    )

                    keywords: List[str] = []
                    if candidate_keywords:
                        campaign_info = {
                            "name": SIM_CONFIG.get("campaign_name", ""),
                            "market": SIM_CONFIG.get("campaign_market", ""),
                            "summary": SIM_CONFIG.get("campaign_summary", ""),
                        }
                        keywords = await crisis_engine.select_relevant_keywords(
                            crisis, candidate_keywords, campaign_info, model,
                            n=n_target,
                        )

                    if keywords:
                        crisis.interest_keywords = list(keywords)
                        for aid in range(len(profiles)):
                            interest_tracker.inject_crisis_interests(
                                aid,
                                {"keywords": keywords, "weight": crisis.severity,
                                 "source": f"crisis:{crisis.crisis_id}"},
                                round_num,
                            )
                        _preview = ", ".join(keywords[:5])
                        _suffix = "..." if len(keywords) > 5 else ""
                        print(
                            f"   🔀 [CRISIS] {len(candidate_keywords)} extracted "
                            f"→ {len(keywords)} campaign-relevant ({_preview}"
                            f"{_suffix}) injected at weight={crisis.severity:.2f}"
                        )
                    else:
                        print(
                            "   ⚠️ [CRISIS] LLM keyword pipeline failed — "
                            "skipping interest perturbation"
                        )

                # D. Log to traces (read for trace_count tracking only —
                # agent content actions của round sẽ được dispatch tới Zep
                # ở cuối round)
                new_traces = read_new_traces(DB_PATH, trace_count)
                trace_count += len(new_traces)

            # Write crisis log to file for API/reporting + sync the cached
            # `crisis_triggered_count` on the meta.db row so list views see
            # the latest count without re-parsing the file.
            if events_this_round and SIM_DIR_ARG:
                crisis_log_path = os.path.join(SIM_DIR_ARG, "crisis_log.json")
                try:
                    atomic_write_json(crisis_log_path, crisis_engine.get_crisis_log())
                except Exception:
                    pass
                # Use the canonical sim_id from config.json (set by /prepare)
                # rather than the local fallback derived from --group-id, so
                # the meta.db row gets updated regardless of how the
                # subprocess was launched.
                _meta_sid = SIM_CONFIG.get("sim_id") or sim_id
                try:
                    from ecosim_common.metadata_index import update_sim_crisis_status
                    update_sim_crisis_status(
                        _meta_sid,
                        triggered_count=len(crisis_engine.get_crisis_log()),
                    )
                except Exception as _me:
                    print(f"   WARN: meta.db crisis count sync fail: {_me}")

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
        _period_mult = _period_mult_for_round(round_num)
        poster_ids = set()
        for agent_id, agent in all_agents:
            profile = profiles[agent_id] if agent_id < len(profiles) else {}
            _mods = mbti_modifiers.get(agent_id, {})
            if should_post(
                profile,
                _rng,
                post_mult=_mods.get("post_mult", 1.0),
                period_mult=_period_mult,
                hours_per_round=HOURS_PER_ROUND,
            ):
                poster_ids.add(agent_id)
        if _period_mult != 1.0:
            print(f"   [TIME] hour≈{int((round_num*HOURS_PER_ROUND)%24)}, period_mult={_period_mult:.2f}")
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

                # Crisis persona injection at trigger round only — full
                # imperative modifier appended to persona. Subsequent rounds
                # rely on perturbed interest vector + agent memory to keep
                # crisis salience alive (no explicit prompt directive).
                if events_this_round:
                    for crisis in events_this_round:
                        crisis_ctx = crisis_engine.get_persona_modifier(crisis)
                        agent_persona += f"\n\nBREAKING NEWS: {crisis_ctx}"

                # Inject social graph context into persona (Phase 5)
                if graph_helper:
                    _social = await graph_helper.get_social_context(agent_name)
                    if _social:
                        agent_persona += f"\n\nSocial context: {_social}"

                # Memory injection (Phase 1 enhancement)
                mem_ctx = agent_memory.get_context(agent_id) if agent_memory else ""

                _interest_kws = []
                if interest_tracker:
                    try:
                        _interest_kws = [
                            kw for kw, _w in interest_tracker.get_top_interests(agent_id, 5)
                        ]
                    except Exception:
                        _interest_kws = []

                # Crisis directive at trigger round only. Pick the highest-
                # severity crisis if multiple fire at the same round.
                _crisis_directive = ""
                _crisis_intensity = "context_only"
                if events_this_round:
                    top_crisis = max(events_this_round, key=lambda c: c.severity)
                    _crisis_directive = crisis_engine.get_short_directive(top_crisis)
                    _crisis_intensity = "strong"

                post_content = await _generate_post_content(
                    model, agent_persona, topic,
                    memory_context=mem_ctx,
                    interest_keywords=_interest_kws,
                    crisis_directive=_crisis_directive,
                    crisis_intensity=_crisis_intensity,
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
                current_round=round_num,
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

        # --- Generate LLM comments in parallel (Tier B M1) ---
        # Thu thập tất cả comment tasks với context → gather() bó cụm 10-song-song
        # để tránh 40-agent × 3s serial (~2 phút). Sau đó gắn kết quả về agent.
        print(f"   Generating {comment_count} comments via LLM (parallel)...", flush=True)

        # Crisis directive shared across all commenters at trigger round.
        # Subsequent rounds: no directive — perturbed interest vector +
        # persona memory keep crisis salience alive.
        if events_this_round and crisis_engine:
            _top_crisis = max(events_this_round, key=lambda c: c.severity)
            _round_crisis_directive = crisis_engine.get_short_directive(_top_crisis)
            _round_crisis_intensity = "strong"
        else:
            _round_crisis_directive = ""
            _round_crisis_intensity = "context_only"

        comment_tasks = []           # list[(agent_key, post_id, coroutine)]
        for (agent, agent_id), plans in agent_action_plans.items():
            _cdir = _round_crisis_directive
            _cintens = _round_crisis_intensity
            for plan in plans:
                if plan[0] != "create_comment":
                    continue
                _, post_id, persona, *extra = plan
                mem_ctx = extra[0] if extra else ""
                post_content = _get_post_content(DB_PATH, post_id)
                _ckws = []
                if interest_tracker:
                    try:
                        _ckws = [
                            kw for kw, _w in interest_tracker.get_top_interests(agent_id, 5)
                        ]
                    except Exception:
                        _ckws = []
                comment_tasks.append((
                    (agent, agent_id),
                    post_id,
                    _generate_comment(
                        model, persona, post_content,
                        memory_context=mem_ctx,
                        interest_keywords=_ckws,
                        crisis_directive=_cdir,
                        crisis_intensity=_cintens,
                    ),
                ))

        # Gather với semaphore giới hạn concurrency 10
        _sem = asyncio.Semaphore(10)
        async def _run_with_cap(coro):
            async with _sem:
                try:
                    return await coro
                except Exception as _e:
                    return None

        comment_results: List[Optional[str]] = await asyncio.gather(
            *(_run_with_cap(c) for _, _, c in comment_tasks)
        )

        # Map kết quả về từng agent
        generated_comments: Dict = defaultdict(list)  # agent_key → [(post_id, content)]
        for (key, post_id, _coro), result in zip(comment_tasks, comment_results):
            if result:
                generated_comments[key].append((post_id, result))

        # Assemble final_actions
        final_actions = {}
        total_comments_generated = 0
        for (agent, agent_id), plans in agent_action_plans.items():
            action_list = []
            gens = dict(generated_comments.get((agent, agent_id), []))
            for plan in plans:
                if plan[0] == "like_post":
                    action_list.append(ManualAction(
                        action_type=ActionType.LIKE_POST,
                        action_args={"post_id": plan[1]},
                    ))
                elif plan[0] == "create_comment":
                    post_id = plan[1]
                    comment = gens.get(post_id)
                    if comment:
                        action_list.append(ManualAction(
                            action_type=ActionType.CREATE_COMMENT,
                            action_args={"post_id": post_id, "content": comment},
                        ))
                        engagement_tracker.record_comment(agent_id, post_id)
                        total_comments_generated += 1

            if not action_list:
                action_list.append(ManualAction(
                    action_type=ActionType.DO_NOTHING,
                    action_args={},
                ))
            final_actions[agent] = action_list

        print(f"   Generated {total_comments_generated}/{comment_count} comments (parallel)", flush=True)

        # --- Single env.step() with all actions ---
        print(f"   Executing all interactions in 1 env.step()...", flush=True)
        try:
            await env.step(final_actions)
        except Exception as e:
            print(f"   ERROR in Phase 2 round {round_num}: {e}", flush=True)

        _write_progress(round_num, NUM_ROUNDS, "running")

        # Read new traces from SQLite. Counts here reflect actually-persisted
        # actions (OASIS rejects e.g. duplicate likes; the planned counts
        # above can over-report). new_traces also includes Phase 1 posts
        # since trace_count was last advanced before the round.
        new_traces = read_new_traces(DB_PATH, trace_count)
        trace_count += len(new_traces)
        _phase2_likes = sum(
            1 for t in new_traces if t.get("action_type") == "like_post"
        )
        _phase2_comments = sum(
            1 for t in new_traces if t.get("action_type") == "create_comment"
        )
        print(
            f"   [Phase 2] Done: {_phase2_likes}/{likes_count} likes + "
            f"{_phase2_comments}/{total_comments_generated} comments "
            f"succeeded",
            flush=True,
        )

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
        _progress_data = {"current_round": round_num, "total_rounds": NUM_ROUNDS, "status": "running"}
        if crisis_engine:
            _progress_data["crisis_summary"] = crisis_engine.get_summary()
        if SIM_DIR_ARG:
            try:
                atomic_write_json(os.path.join(SIM_DIR_ARG, "progress.json"), _progress_data)
            except Exception as e:
                print(f"   WARNING: failed to write progress.json: {e}")
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

            # Phase 3.1: persist round summaries vào ecosim_agent_memory graph
            # nếu enable_graph_cognition=true. Best-effort, silent fail.
            if agent_mem_graph_active:
                try:
                    from agent_memory_graph import write_round_summary
                    for _aid in range(len(profiles)):
                        _ctx = agent_memory.get_context(_aid)
                        # get_context trả nhiều rounds — extract dòng cuối cho round vừa rồi
                        _last = _ctx.strip().split("\n")[-1] if _ctx else ""
                        if _last.startswith(f"Round {round_num}:"):
                            write_round_summary(
                                sim_id, _aid, round_num, _last,
                                falkor_host=FALKOR_HOST, falkor_port=FALKOR_PORT,
                            )
                except Exception as _me:
                    print(f"   WARN: agent_memory_graph write fail: {_me}")

            # Tier B C6: dump memory_stats.json cho debugging + post-sim analysis
            if SIM_DIR_ARG:
                try:
                    agent_memory.dump_stats(
                        os.path.join(SIM_DIR_ARG, "memory_stats.json"),
                        num_agents=len(profiles),
                        current_round=round_num,
                    )
                except Exception as _me:
                    print(f"   WARN: memory_stats dump failed: {_me}")

        # Tier B H4: persist evolved personas + insights back to profiles.json
        # mỗi cycle reflection (để sim restart có thể resume state).
        if reflection and SIM_DIR_ARG and round_num % max(1, reflection.interval) == 0:
            try:
                _dirty = False
                for aid in range(len(profiles)):
                    base = profiles[aid].get("persona", "")
                    evolved = reflection.get_evolved_persona(aid, base)
                    if evolved != base:
                        profiles[aid]["persona_evolved"] = evolved
                        profiles[aid]["reflection_insights"] = list(
                            reflection._insights.get(aid, [])
                        )
                        _dirty = True
                if _dirty:
                    atomic_write_json(PROFILE_PATH, profiles)
                    print(f"   [REFLECT] Persisted evolved personas → {PROFILE_PATH}")

                # Phase 3.1: persist reflection insights vào ecosim_agent_memory
                if agent_mem_graph_active:
                    try:
                        from agent_memory_graph import write_reflection_insights
                        for aid in range(len(profiles)):
                            ins = list(reflection._insights.get(aid, []))
                            if ins:
                                write_reflection_insights(
                                    sim_id, aid, round_num, ins,
                                    falkor_host=FALKOR_HOST, falkor_port=FALKOR_PORT,
                                )
                    except Exception as _re:
                        print(f"   WARN: agent_memory_graph reflection persist fail: {_re}")

                # Phase 4: master mutation từ reflection insights
                # Best-effort, async LLM call. Query FalkorDB master graph cho entity names.
                try:
                    from sim_master_mutator import (
                        analyze_reflection_for_mutations, apply_mutations,
                    )
                    _master_cid = SIM_CONFIG.get("campaign_id", "")
                    _master_names = set()
                    if _master_cid:
                        try:
                            from falkordb import FalkorDB
                            _fdb = FalkorDB(
                                host=os.environ.get("FALKORDB_HOST", "localhost"),
                                port=int(os.environ.get("FALKORDB_PORT", 6379)),
                            )
                            if _master_cid in _fdb.list_graphs():
                                _g = _fdb.select_graph(_master_cid)
                                _r = _g.query("MATCH (n:Entity) WHERE n.name IS NOT NULL RETURN n.name")
                                _master_names = {row[0] for row in _r.result_set if row[0]}
                        except Exception as _qe:
                            print(f"   WARN: master entity name query fail: {_qe}")
                    if _master_names:
                        from ecosim_common.llm_client import LLMClient
                        _llm = LLMClient()
                        import asyncio as _asyncio
                        _loop = _asyncio.new_event_loop()
                        for aid in range(len(profiles)):
                            ins = list(reflection._insights.get(aid, []))
                            if not ins:
                                continue
                            _muts = _loop.run_until_complete(
                                analyze_reflection_for_mutations(
                                    ins, _master_names,
                                    round_num=round_num, agent_id=aid, llm_client=_llm,
                                )
                            )
                            if _muts:
                                _applied = apply_mutations(
                                    sim_id, SIM_DIR_ARG, _muts,
                                    round_num=round_num, agent_id=aid,
                                    falkor_host=FALKOR_HOST, falkor_port=FALKOR_PORT,
                                )
                                if _applied > 0:
                                    print(f"   [MUTATE] agent {aid}: {_applied} master mutations applied")
                        _loop.close()
                except Exception as _me:
                    print(f"   WARN: master mutation cycle fail: {_me}")
            except Exception as _pe:
                print(f"   WARN: evolved persona persist failed: {_pe}")

        # Update interest vectors from this round's engagement (Tier B H5: wrap try/except)
        if interest_tracker:
            try:
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
                        try:
                            entities = await graph_helper.get_interest_entities(aname)
                        except Exception as _ge:
                            entities = None
                            logging.getLogger("ecosim").debug(
                                "graph entities fetch failed agent %d: %s", aid, _ge
                            )
                        if entities:
                            agent_graph_entities[aid] = entities[:2]

                # Update all agents' interest vectors
                for aid in range(len(profiles)):
                    contents = agent_engaged_posts.get(aid, [])
                    graph_ents = agent_graph_entities.get(aid, [])
                    try:
                        interest_tracker.update_after_round(
                            aid, round_num, contents, graph_entities=graph_ents
                        )
                    except Exception as _de:
                        logging.getLogger("ecosim").warning(
                            "drift update failed agent %d round %d: %s", aid, round_num, _de
                        )

                total_interests = sum(interest_tracker.get_drift_count(i)
                                      for i in range(len(profiles)))
                print(f"   Interest vectors: {total_interests} total interests tracked")
            except Exception as _drift_e:
                print(f"   WARN: interest drift phase failed: {_drift_e}")

        # ── Phase 15.tracking: cognitive tracking cho list of agents ──
        # Re-resolve list từ SIM_CONFIG (đã set ở init phase trên)
        _round_tracked_ids = SIM_CONFIG.get("tracked_agent_ids") or []
        if not _round_tracked_ids:
            _legacy = SIM_CONFIG.get("tracked_agent_id", -1)
            if _legacy >= 0:
                _round_tracked_ids = [_legacy]
        _round_tracked_ids = [i for i in _round_tracked_ids if 0 <= i < len(profiles)]

        if _round_tracked_ids and SIM_DIR_ARG:
            try:
                from agent_tracking_writer import write_agent_round
                for _tid in _round_tracked_ids:
                    _tpr = profiles[_tid]
                    _basepr = _tpr.get("persona", "")
                    _evolvedpr = reflection.get_evolved_persona(_tid, _basepr) if reflection else _basepr
                    _ctpr = {}
                    _ivpr = []
                    _sqpr = []
                    if interest_tracker:
                        _t = interest_tracker.get_traits(_tid)
                        if _t:
                            _ctpr = _t.to_dict()
                        _ivpr = [
                            {**it,
                             "trending": it.get("engagement_count", 0) > 0,
                             "is_new": it.get("first_seen") == round_num}
                            for it in interest_tracker.get_items(_tid)
                        ]
                        _sqpr = [
                            {"weight": w, "query": q}
                            for q, w in interest_tracker.get_search_queries(_tid, n=5)
                        ]
                    _mempr = agent_memory.get_context(_tid) if agent_memory else ""
                    # Query Graph Cognitive Helper for the tracked agent's
                    # social context. Frontend "Graph context" panel reads
                    # the resulting string from tracking.jsonl. Previous
                    # version hardcoded "" here even when graph_helper was
                    # active — frontend always saw Empty regardless of toggle.
                    _gctx_pr = ""
                    if graph_helper:
                        try:
                            _gctx_pr = await graph_helper.get_social_context(
                                AGENT_NAMES.get(_tid, f"Agent {_tid}")
                            )
                        except Exception:
                            _gctx_pr = ""
                    write_agent_round(
                        SIM_DIR_ARG,
                        round_num=round_num,
                        agent_id=_tid,
                        agent_name=AGENT_NAMES.get(_tid, f"Agent {_tid}"),
                        mbti=_tpr.get("mbti", ""),
                        base_persona=_basepr,
                        evolved_persona=_evolvedpr,
                        cognitive_traits=_ctpr,
                        interest_vector=_ivpr,
                        search_queries=_sqpr,
                        mbti_modifiers=mbti_modifiers.get(_tid, {}),
                        memory=_mempr,
                        graph_context=_gctx_pr,
                        actions=[],
                    )
            except Exception as _je:
                print(f"   WARN: JSONL tracking write fail: {_je}")
        # backward-compat single id alias dùng cho legacy text writer block dưới
        _tracked_id = _round_tracked_ids[0] if _round_tracked_ids else -1

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

        # Phase 15: end-of-round Zep section dispatch (Node 1-10).
        # Block ~30-60s đợi Zep extract xong → round N+1 cognitive query thấy
        # round N data. Per-action sections trong batch → Zep dedup mạnh.
        if zep_section_enabled:
            _enrich_traces_for_kg_batch(new_traces, DB_PATH, AGENT_NAMES)
            try:
                from sim_zep_section_writer import write_round_sections_via_zep
                _round_stats = await write_round_sections_via_zep(
                    round_num=round_num, traces=new_traces,
                    agent_names=AGENT_NAMES, agent_profiles=AGENT_PROFILES,
                    sim_id=graph_name, llm=zep_llm_client,
                    falkor_host=FALKOR_HOST, falkor_port=FALKOR_PORT,
                )
                print(f"   Zep r{round_num}: {_round_stats.get('status')} "
                      f"sections={_round_stats.get('sections_submitted', 0)} "
                      f"+{_round_stats.get('entities_added', 0)} entities "
                      f"+{_round_stats.get('edges_added', 0)} edges "
                      f"reroute=({_round_stats.get('rerouted_out', 0)}/"
                      f"{_round_stats.get('rerouted_in', 0)}/"
                      f"{_round_stats.get('cleaned_zep_agents', 0)})")
            except Exception as _e:
                print(f"   [WARN] Zep r{round_num} dispatch failed: {_e}")

    # Final progress
    _write_progress(NUM_ROUNDS, NUM_ROUNDS, "completed")
    _write_actions()
    print(f"\nAll {NUM_ROUNDS} rounds completed. Total traces: {trace_count}")

    # ----------------------------------------------------------
    # 9. Phase 15 finalize: build indices + delete Zep graph (Node 11-12)
    # ----------------------------------------------------------
    if zep_section_enabled:
        print("\n[FLUSH] Phase 15 finalize: build indices + cleanup Zep graph...")
        try:
            from sim_zep_section_writer import finalize_sim_post_run
            _fin_stats = await finalize_sim_post_run(
                sim_id=graph_name,
                falkor_host=FALKOR_HOST, falkor_port=FALKOR_PORT,
            )
            print(f"   [OK] Finalize: indices_built={_fin_stats.get('indices_built')} "
                  f"zep_deleted={_fin_stats.get('zep_graph_deleted')}")
        except Exception as _e:
            print(f"   [WARN] Phase 15 finalize failed: {_e}")

    # Close graph cognitive helper
    if graph_helper:
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
    if zep_section_enabled:
        print(f"   Simulation ID: {sim_id}")
        print(f"   FalkorDB: falkor://{FALKOR_HOST}:{FALKOR_PORT}")
        print(f"   Sim graph: {graph_name}")
    print(f"   Graph Cognition: {'ENABLED' if graph_helper else 'disabled'}")
    print(f"{'='*60}")
    print(f"\n[ANALYZE] To analyze results:")
    print(f"   SQLite:   SELECT * FROM trace ORDER BY created_at;")
    if zep_section_enabled:
        print(f"   FalkorDB: graphiti.search('Shopee Black Friday', group_ids=['{graph_name}'])")


if __name__ == "__main__":
    asyncio.run(main())


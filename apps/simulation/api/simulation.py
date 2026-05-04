"""
Simulation API — OASIS simulation lifecycle management.

Endpoints:
  POST /api/sim/prepare        — Generate profiles + config
  POST /api/sim/start          — Start OASIS simulation
  GET  /api/sim/status         — Get simulation status
  GET  /api/sim/list           — List all simulations
  GET  /api/sim/{id}/profiles  — Get agent profiles
  GET  /api/sim/{id}/config    — Get simulation config
  GET  /api/sim/{id}/actions   — Get simulation actions
  GET  /api/sim/{id}/progress  — Get progress
"""
import asyncio
import json
import logging
import os
import subprocess
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("sim-svc.simulation")

router = APIRouter(prefix="/api/sim", tags=["Simulation"])

# ── Config ──
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # apps/simulation
def _find_repo_root(start):
    import pathlib as _pl
    here = _pl.Path(start).resolve()
    for parent in [here, *here.parents]:
        if (parent / "libs" / "ecosim-common" / "src").is_dir():
            return str(parent)
    return os.path.dirname(os.path.dirname(start))
ECOSIM_ROOT = _find_repo_root(SCRIPT_DIR)
SIM_DIR = os.path.join(ECOSIM_ROOT, "data", "simulations")
UPLOAD_DIR = os.path.join(ECOSIM_ROOT, os.getenv("UPLOAD_DIR", "uploads"))
OASIS_VENV_PYTHON = os.path.join(SCRIPT_DIR, ".venv", "Scripts", "python.exe")

os.makedirs(SIM_DIR, exist_ok=True)


# ── State Management ──
class SimStatus(str, Enum):
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SimState(BaseModel):
    sim_id: str
    status: SimStatus = SimStatus.CREATED
    campaign_id: str = ""
    num_agents: int = 0
    current_round: int = 0
    total_rounds: int = 24
    output_dir: str = ""
    error: str = ""
    created_at: str = ""
    group_id: str = ""


_simulations: Dict[str, SimState] = {}
_processes: Dict[str, subprocess.Popen] = {}

# Phase 12 #2: thread-safe state — protect _simulations + _processes against
# concurrent /start, /delete, /status, monitor thread races. RLock cho phép
# nested acquisition trong cùng thread (vd start_simulation gọi nhiều helpers).
import threading as _threading
_state_lock = _threading.RLock()


def _get_or_load_state(sim_id: str) -> Optional[SimState]:
    """Phase 12 #2: query meta.db nếu in-memory dict miss (sau service restart).

    Single source of truth = meta.db. In-memory `_simulations` chỉ là cache
    cho Popen handle + transient fields (error string).

    Returns None nếu sim không tồn tại trong meta.db.
    """
    with _state_lock:
        st = _simulations.get(sim_id)
        if st:
            return st

    # Cache miss → load from DB
    try:
        from ecosim_common.metadata_index import get_simulation
        from ecosim_common.path_resolver import resolve_simulation_paths
        row = get_simulation(sim_id)
        if not row:
            return None

        # Map DB status string → SimStatus enum
        status_str = (row.get("status") or "created").lower()
        try:
            sim_status = SimStatus(status_str)
        except Exception:
            sim_status = SimStatus.READY

        # Resolve sim_dir qua path_resolver (DB-backed, nested layout)
        try:
            paths = resolve_simulation_paths(sim_id)
            sim_dir = paths.get("sim_dir") or ""
        except Exception:
            sim_dir = ""

        kg_graph_name = sim_id if sim_id.startswith("sim_") else f"sim_{sim_id}"

        st = SimState(
            sim_id=sim_id,
            status=sim_status,
            campaign_id=row.get("cid", "") or "",
            num_agents=int(row.get("num_agents", 0) or 0),
            total_rounds=int(row.get("num_rounds", 0) or 0),
            current_round=int(row.get("current_round", 0) or 0),
            output_dir=sim_dir,
            created_at=row.get("created_at", "") or "",
            group_id=kg_graph_name,
        )
        with _state_lock:
            # Double-check pattern — another thread may have populated cache
            cached = _simulations.get(sim_id)
            if cached:
                return cached
            _simulations[sim_id] = st
        return st
    except Exception as e:
        logger.debug("_get_or_load_state(%s) DB lookup fail: %s", sim_id, e)
        return None


# Phase 15: _finalize_zep_with_retry removed. Finalize (Node 11-12 build indices
# + delete Zep graph) chạy inline trong run_simulation.py sau round loop.


def _sim_paths(sim_id: str) -> Dict[str, str]:
    """Single source of truth for sim file paths in API handlers.

    Resolves all paths from meta.db (the row populated by `/prepare` via
    `populate_simulation_paths`). Falls back to convention if the meta.db
    row is missing or stale (e.g. the row hasn't been backfilled yet),
    then to in-memory `_simulations[sid].output_dir` as a last resort.

    Every endpoint that touches a sim file should go through this helper —
    that way the column in meta.db is the single canonical record of where
    each artifact lives, instead of every handler hardcoding its own
    `os.path.join(sim_dir, "X.json")`.
    """
    try:
        from ecosim_common.path_resolver import resolve_simulation_paths
        return dict(resolve_simulation_paths(sim_id, fallback=True))
    except Exception as e:
        logger.debug("_sim_paths(%s) resolver fail, using state fallback: %s", sim_id, e)
        state = _simulations.get(sim_id)
        sim_dir = state.output_dir if state else os.path.join(SIM_DIR, sim_id)
        return {
            "sim_dir": sim_dir,
            "config_path": os.path.join(sim_dir, "config.json"),
            "profiles_path": os.path.join(sim_dir, "profiles.json"),
            "actions_path": os.path.join(sim_dir, "actions.jsonl"),
            "oasis_db_path": os.path.join(sim_dir, "oasis_simulation.db"),
            "progress_path": os.path.join(sim_dir, "progress.json"),
            "memory_stats_path": os.path.join(sim_dir, "memory_stats.json"),
            "tracking_path": os.path.join(sim_dir, "analysis", "tracking.jsonl"),
            "tracking_legacy_path": os.path.join(sim_dir, "agent_tracking.txt"),
            "sentiment_path": os.path.join(sim_dir, "analysis", "sentiment.json"),
            "report_log_path": os.path.join(sim_dir, "report", "agent_log.jsonl"),
            "crisis_log_path": os.path.join(sim_dir, "crisis_log.json"),
            "crisis_pending_path": os.path.join(sim_dir, "pending_crisis.json"),
            "simulation_log_path": os.path.join(sim_dir, "simulation.log"),
            "campaign_context_path": os.path.join(sim_dir, "campaign_context.txt"),
        }


# ── Request Models ──
class CrisisEventDef(BaseModel):
    """Crisis event definition for scheduled or real-time injection.

    One-shot at `trigger_round`. The LLM extracts `n_keywords` keyphrases
    from title+description+affected_domains at trigger time and injects
    them into every agent's interest vector with weight = severity.
    Longevity is owned by `InterestVectorTracker.update_after_round`.
    """
    trigger_round: int = 1
    crisis_type: str = "custom"  # price_change|scandal|news|competitor|regulation|positive_event|custom
    title: str = "Crisis Event"
    description: str = ""
    severity: float = 0.5        # 0.0 (mild) → 1.0 (catastrophic)
    affected_domains: List[str] = []
    sentiment_shift: str = "negative"  # negative|positive|mixed
    # How many keyphrases the LLM should extract at trigger time (UI tunable).
    n_keywords: int = 5


class PrepareRequest(BaseModel):
    campaign_id: str
    num_agents: int = 10
    num_rounds: int = 3
    group_id: str = ""
    cognitive_toggles: Dict[str, bool] = {}
    # Phase 15.tracking: multi-agent tracking. Default = [0, 1] (track 2 agents
    # đầu tiên). Set [] để disable tracking. tracked_agent_id (int) giữ làm
    # backward-compat alias — tự động convert thành [tracked_agent_id].
    tracked_agent_ids: List[int] = [0, 1]
    tracked_agent_id: Optional[int] = None  # legacy single-agent field
    crisis_events: List[CrisisEventDef] = []  # Scheduled crisis events
    seed: Optional[int] = None  # Reproducibility seed cho rng + parquet sampling
    # Per-sim override cho ZEP_SIM_RUNTIME env. None = inherit env default.
    # Khi true → content actions (post/comment) được Zep extract MENTIONS_BRAND/
    # DISCUSSES bridge edges tới master entities. Yêu cầu ZEP_API_KEY set.
    enable_zep_runtime: Optional[bool] = None

class StartRequest(BaseModel):
    sim_id: str
    group_id: str = ""


# ── Profile Generator (Tier B) ──
import random as _random
import re as _re

from ecosim_common.agent_schemas import (
    AgentProfile,
    BatchEnrichmentResponse,
    EnrichedAgentLLMOutput,
    MBTI_TYPES,
)
from ecosim_common.llm_client import LLMClient
from ecosim_common.name_pool import NamePool
from ecosim_common.parquet_reader import ParquetProfileReader

# Parquet source for rich persona data (resolve relative to ECOSIM_ROOT)
_PARQUET_PATH = os.path.join(ECOSIM_ROOT, "data", "dataGenerator", "profile.parquet")

# Regex để strip PII và ký tự gây LLM-format injection khỏi parquet text
_PII_EMAIL_RE = _re.compile(r"[\w\.\-+]+@[\w\.\-]+\.\w+")
_PII_PHONE_RE = _re.compile(r"\b\+?\d[\d\s\-().]{7,}\d\b")
_BRACES_RE = _re.compile(r"[{}]")
_MAX_PERSONA_CHARS = 600


def _sanitize_persona(raw: str) -> str:
    """Làm sạch persona từ parquet trước khi đưa vào LLM prompt:
    - Strip email / phone
    - Escape `{` `}` để không vỡ `.format()`
    - Truncate ≤ 600 chars
    """
    if not raw:
        return ""
    s = _PII_EMAIL_RE.sub("[email]", raw)
    s = _PII_PHONE_RE.sub("[phone]", s)
    s = _BRACES_RE.sub("", s)
    s = " ".join(s.split())  # collapse whitespace
    if len(s) > _MAX_PERSONA_CHARS:
        s = s[:_MAX_PERSONA_CHARS].rsplit(" ", 1)[0] + "..."
    return s


async def _get_consumer_campaign_context(campaign_spec: dict, campaign_id: str = "") -> str:
    """Query Graphiti for campaign knowledge and use LLM to rewrite
    into a consumer-friendly summary (discarding KPIs, risks, etc.).

    `campaign_id` được dùng làm FalkorDB graph name (master KG của campaign).
    Nếu không pass → fallback đọc từ campaign_spec; nếu vẫn rỗng → skip Graphiti.
    """
    campaign_name = campaign_spec.get("name", "")
    campaign_summary = campaign_spec.get("summary", "")
    timeline = campaign_spec.get("timeline", "")
    market = campaign_spec.get("market", "")
    cid = campaign_id or campaign_spec.get("campaign_id", "")

    # Try Graphiti for richer context (master KG of campaign)
    graphiti_facts = ""
    if cid:
        try:
            from ecosim_common.graphiti_factory import make_graphiti, make_falkor_driver

            driver = make_falkor_driver(host=FALKOR_HOST, port=FALKOR_PORT, database=cid)
            graphiti = make_graphiti(driver)
            # Note: `search_method=SearchMethod.COMBINED_HYBRID_SEARCH_CROSS_ENCODER`
            # was removed in current graphiti_core. The basic `search()` already
            # combines BM25 + vector with cross-encoder reranking by default.
            # For per-layer config control use `graphiti.search_(config=...)`.
            results = await graphiti.search(
                query=f"{campaign_name} promotions deals products discounts",
                num_results=10,
            )
            facts = [getattr(r, "fact", "") for r in results if getattr(r, "fact", "")]
            if facts:
                graphiti_facts = " ".join(facts)
            await graphiti.close()
        except Exception as e:
            logger.warning("Graphiti query for campaign context failed: %s", e)

    # Build raw material for LLM
    raw_info = f"Campaign: {campaign_name}."
    if market:
        raw_info += f" Market: {market}."
    if timeline:
        raw_info += f" Timeline: {timeline}."
    if campaign_summary:
        raw_info += f" Summary: {campaign_summary}"
    if graphiti_facts:
        raw_info += f" Additional facts from knowledge graph: {graphiti_facts}"

    # Use LLM to rewrite from consumer perspective
    try:
        import openai
        client = openai.AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=300,
            temperature=0.7,
            messages=[
                {"role": "system", "content": (
                    "You are a consumer who reads social media. Rewrite the following "
                    "campaign information into a SHORT paragraph (3-5 sentences) that "
                    "describes what a regular consumer would know and care about. "
                    "Focus on: what the campaign offers, what products/discounts are "
                    "available, when it happens, and why it's interesting. "
                    "OMIT all internal business metrics, KPIs, risks, seller data, "
                    "and stakeholder lists. Write in English."
                )},
                {"role": "user", "content": raw_info},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("LLM campaign rewrite failed: %s — using fallback", e)
        # Fallback: just use name + summary (no KPIs/risks)
        fallback = f"{campaign_name}"
        if timeline:
            fallback += f" ({timeline})"
        if campaign_summary:
            fallback += f" — {campaign_summary}"
        return fallback


# ── Domain extraction + LLM batch enrichment ──

_DOMAIN_EXTRACT_PROMPT = """\
You are helping sample consumer profiles from a large dataset for a marketing simulation.
Given the campaign info below, extract 3-8 SHORT domain keywords (1-3 words each) that describe
the kinds of consumers whose expertise or interests would be RELEVANT to this campaign.
Examples: "E-commerce", "Healthcare", "Gaming", "Finance", "Food & Cooking", "Tech".

Return STRICT JSON: {"domains": ["<domain1>", "<domain2>", ...]}

Campaign info:
{campaign_info}
"""

_ENRICH_SYSTEM = """\
You are generating realistic social-media user profiles for a marketing simulation.
You receive raw persona text from a real dataset. For each persona you must:
1. Rewrite it in 150-200 English words, embedding the Vietnamese name naturally.
2. Add ONE natural sentence about how this person would react to / engage with the campaign.
3. Infer an MBTI type (16 types) from the persona's traits — DO NOT pick randomly.
4. Infer age 18-70 consistent with their expertise level.
5. Extract 3-7 short interest keywords (lowercase, 1-2 words each).
6. Keep the person's existing interests and profession intact.

Return STRICT JSON (no prose, no markdown fences):
{"profiles":[{"id":0,"enriched_persona":"...","bio":"<=160 chars","age":28,"mbti":"INTJ","interests":["..."]}, ...]}

All string values MUST NOT contain literal newlines — use spaces.
"""

_ENRICH_USER_TMPL = """\
Campaign context (for agent awareness):
{consumer_ctx}

Personas to enrich ({count} total). Each entry has a pre-assigned gender and Vietnamese name.

{personas_block}
"""


async def _extract_campaign_domains(
    llm: LLMClient, campaign_spec: dict
) -> List[str]:
    """Hỏi LLM domain keywords phù hợp campaign (1 call, cached results nếu có thể)."""
    info_parts = [
        f"Name: {campaign_spec.get('name', '')}",
        f"Type: {campaign_spec.get('campaign_type', '')}",
        f"Market: {campaign_spec.get('market', '')}",
        f"Summary: {campaign_spec.get('summary', '')}",
    ]
    raw = "\n".join(p for p in info_parts if p.split(": ", 1)[-1].strip())
    if not raw:
        return []
    try:
        resp = await llm.chat_json_async(
            messages=[
                {"role": "system", "content": "Return STRICT JSON."},
                {"role": "user", "content": _DOMAIN_EXTRACT_PROMPT.format(campaign_info=raw)},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        domains = resp.get("domains", []) if isinstance(resp, dict) else []
        return [d for d in domains if isinstance(d, str) and d.strip()][:8]
    except Exception as e:
        logger.warning("Domain extraction failed: %s — fallback to random sampling", e)
        return []


def _sample_parquet_60_40(
    n: int,
    domains: List[str],
    seed: Optional[int],
) -> List[dict]:
    """60% domain-relevant + 40% diverse random sampling (Tier B restore)."""
    if not os.path.exists(_PARQUET_PATH):
        logger.warning("Parquet missing at %s — using fallback", _PARQUET_PATH)
        return [
            {"persona": "A regular social media user.", "general_domain": "", "specific_domain": ""}
        ] * n

    reader = ParquetProfileReader(_PARQUET_PATH)
    try:
        if domains:
            n_domain = max(1, int(n * 0.6))
            n_random = n - n_domain
            domain_rows = reader.sample_by_domains(domains, n_domain, seed=seed)
            random_rows = reader.sample_random(n_random, seed=seed) if n_random > 0 else []
            rows = domain_rows + random_rows
            if len(rows) < n:  # parquet returned fewer than asked; top up
                rows += reader.sample_random(n - len(rows), seed=seed)
            return rows[:n]
        return reader.sample_random(n, seed=seed)
    finally:
        reader.close()


async def _enrich_batch_async(
    llm: LLMClient,
    batch_inputs: List[dict],
    consumer_ctx: str,
) -> List[EnrichedAgentLLMOutput]:
    """Gọi LLM cho 1 batch (≤10 agents) và validate response qua Pydantic.

    `batch_inputs` mỗi item: {id, realname, gender, sanitized_persona, general_domain, specific_domain}
    """
    personas_lines = []
    for item in batch_inputs:
        domain_hint = item["general_domain"] or item["specific_domain"] or "general"
        personas_lines.append(
            f"[id={item['id']}] {item['realname']} ({item['gender']}) — domain: {domain_hint}\n"
            f"Raw persona: {item['sanitized_persona']}\n"
        )
    user_msg = _ENRICH_USER_TMPL.format(
        consumer_ctx=consumer_ctx or "(no additional campaign context)",
        count=len(batch_inputs),
        personas_block="\n".join(personas_lines),
    )

    try:
        raw = await llm.chat_json_async(
            messages=[
                {"role": "system", "content": _ENRICH_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.7,
            max_tokens=4000,
        )
        parsed = BatchEnrichmentResponse.model_validate(raw)
        return parsed.profiles
    except Exception as e:
        logger.warning("LLM enrichment batch failed: %s — will rule-based fallback", e)
        return []


def _mbti_from_traits(rng: _random.Random, persona_text: str) -> str:
    """Rule-based MBTI fallback: heuristic keyword match, else random."""
    text = (persona_text or "").lower()
    e_or_i = "E" if any(w in text for w in ("social", "team", "community", "extrovert")) else (
        "I" if any(w in text for w in ("quiet", "introvert", "alone", "solo")) else rng.choice(["E", "I"])
    )
    n_or_s = "N" if any(w in text for w in ("creative", "innovative", "visionary")) else (
        "S" if any(w in text for w in ("practical", "detail", "hands-on")) else rng.choice(["N", "S"])
    )
    t_or_f = "T" if any(w in text for w in ("analytical", "logic", "engineer", "data")) else (
        "F" if any(w in text for w in ("empathy", "caring", "art", "feeling")) else rng.choice(["T", "F"])
    )
    j_or_p = "J" if any(w in text for w in ("planner", "organized", "schedule")) else (
        "P" if any(w in text for w in ("flexible", "spontaneous", "explore")) else rng.choice(["J", "P"])
    )
    return e_or_i + n_or_s + t_or_f + j_or_p


def _balance_mbti(mbtis: List[str], max_ratio: float = 0.30) -> List[str]:
    """Nếu >max_ratio agents cùng MBTI type → đổi bớt sang type ít phổ biến nhất."""
    from collections import Counter
    counts = Counter(mbtis)
    n = len(mbtis)
    limit = max(1, int(n * max_ratio))
    # Snapshot list các type vượt ngưỡng (tránh mutate dict trong lúc iterate)
    over_types = [(mbti, c) for mbti, c in counts.items() if c > limit]
    for mbti, c in over_types:
        indices = [i for i, m in enumerate(mbtis) if m == mbti]
        over = counts[mbti] - limit
        for idx in indices[:over]:
            least = min(MBTI_TYPES, key=lambda t: counts.get(t, 0))
            mbtis[idx] = least
            counts[mbti] -= 1
            counts[least] = counts.get(least, 0) + 1
    return mbtis


def _derive_runtime_fields(
    mbti: str, rng: _random.Random
) -> dict:
    """Từ MBTI + rng, suy ra fields runtime mà simulation loop cần.

    Chỉ giữ field có consumer thực tế trong sim runtime:
    - `posts_per_week` → `interest_feed.get_post_probability()` gate posting
    - `daily_hours`    → `interest_feed.get_feed_size()` size feed
    - `activity_level` → inject vào prompt LLM của interview API
    - `followers`      → re-rank popularity bonus trong feed query

    Removed (verified zero consumer):
    - `posting_probability`: pre-compute nhưng sim recalculate từ posts_per_week
    - `active_hours`: không có hour-gating logic trong sim loop
    """
    is_extrovert = mbti[0] == "E"
    is_perceiver = mbti[3] == "P"

    # posts_per_week: E tăng, I giảm
    base_posts = rng.choice([2, 3, 5, 7])
    posts_per_week = max(1, int(base_posts * (1.3 if is_extrovert else 0.8)))

    # daily_hours: P hay mò nhiều hơn J
    base_hours = rng.choice([0.5, 1.0, 1.5, 2.0, 3.0])
    daily_hours = round(base_hours * (1.2 if is_perceiver else 0.9), 1)

    # activity_level: scalar dùng cho interview LLM context (Mức hoạt động)
    activity_level = min(1.0, posts_per_week / 15.0 + daily_hours / 8.0)
    activity_level = round(min(1.0, max(0.1, activity_level)), 2)

    # follower_count: distribution skewed log-normal-like
    follower_count = rng.choice([
        rng.randint(50, 300),
        rng.randint(300, 1500),
        rng.randint(1500, 5000),
        rng.randint(5000, 20000),
    ])

    return {
        "posts_per_week": posts_per_week,
        "daily_hours": daily_hours,
        "activity_level": activity_level,
        "followers": follower_count,
    }


async def _generate_profiles(
    num_agents: int,
    campaign_spec: dict,
    seed: Optional[int] = None,
) -> list:
    """Tier B: sinh N profile qua 5 bước.

    1. Domain extraction (1 LLM call) → domain keywords cho sampling
    2. Parquet 60/40 sampling (seeded qua REPEATABLE)
    3. Consumer campaign context (1 LLM call — cho tất cả agents dùng chung)
    4. Per-agent LLM enrichment (async batches 10) — persona rewrite + MBTI from signal
    5. Runtime fields derived từ MBTI (active_hours, posting_probability, ...)
    """
    rng = _random.Random(seed)
    llm = LLMClient()

    # Step 1: Domain extraction
    domains = await _extract_campaign_domains(llm, campaign_spec)
    logger.info("Campaign domain keywords: %s", domains)

    # Step 2: Parquet sampling 60/40
    parquet_rows = _sample_parquet_60_40(num_agents, domains, seed)
    logger.info("Sampled %d/%d personas from parquet", len(parquet_rows), num_agents)

    # Step 3: Consumer campaign context (shared) — pass campaign_id để query
    # đúng master KG (graph FalkorDB tên = campaign_id, sau bug fix isolation).
    consumer_ctx = await _get_consumer_campaign_context(
        campaign_spec, campaign_id=campaign_spec.get("campaign_id", "")
    )
    logger.info("Consumer context (%d chars)", len(consumer_ctx))

    # Step 4: Prepare names + genders + sanitize parquet
    name_pool = NamePool(seed=seed)
    agent_slots: List[dict] = []
    for i in range(num_agents):
        pq = parquet_rows[i] if i < len(parquet_rows) else parquet_rows[-1]
        gender = rng.choice(["female", "male"])
        realname = name_pool.pick(gender=gender)
        first_token = realname.split()[-1].lower()
        last_token = realname.split()[0].lower()
        username = f"{first_token}_{last_token}_{rng.randint(100, 999)}"
        agent_slots.append({
            "id": i,
            "realname": realname,
            "username": username,
            "gender": gender,
            "sanitized_persona": _sanitize_persona(pq.get("persona", "")),
            "original_persona": pq.get("persona", ""),
            "general_domain": pq.get("general_domain", ""),
            "specific_domain": pq.get("specific_domain", ""),
        })

    # Step 4b: Async batch enrichment (batches of 10, parallel)
    BATCH = 10
    batches = [agent_slots[i:i + BATCH] for i in range(0, num_agents, BATCH)]
    enriched_tasks = [_enrich_batch_async(llm, b, consumer_ctx) for b in batches]
    enriched_results = await asyncio.gather(*enriched_tasks, return_exceptions=True)

    # Map: id → EnrichedAgentLLMOutput
    id_to_enriched: Dict[int, EnrichedAgentLLMOutput] = {}
    for batch, result in zip(batches, enriched_results):
        if isinstance(result, Exception) or not isinstance(result, list):
            continue
        for e in result:
            if isinstance(e, EnrichedAgentLLMOutput) and any(s["id"] == e.id for s in batch):
                id_to_enriched[e.id] = e

    logger.info(
        "LLM enriched %d/%d agents (rule-based fallback for %d)",
        len(id_to_enriched), num_agents, num_agents - len(id_to_enriched),
    )

    # Step 4c: Rule-based fallback + MBTI balance
    mbtis: List[str] = []
    for slot in agent_slots:
        enriched = id_to_enriched.get(slot["id"])
        if enriched:
            mbtis.append(enriched.mbti)
        else:
            mbtis.append(_mbti_from_traits(rng, slot["sanitized_persona"]))
    mbtis = _balance_mbti(mbtis, max_ratio=0.30)

    # Step 5: Assemble final profiles with runtime fields
    profiles: list = []
    for i, slot in enumerate(agent_slots):
        enriched = id_to_enriched.get(slot["id"])
        mbti = mbtis[i]
        if enriched is not None:
            age = enriched.age
            persona_text = enriched.enriched_persona
            bio_text = enriched.bio
            interests = enriched.interests
        else:
            age = rng.randint(22, 55)
            # Fallback persona: concat sanitized parquet + consumer_ctx (cũ)
            persona_text = (
                f"{slot['realname']}, a {age}-year-old {slot['gender']} from Vietnam. "
                f"{slot['sanitized_persona']} "
                f"Campaign awareness: {consumer_ctx[:200]}"
            ).strip()
            bio_text = (slot["sanitized_persona"][:150] or f"{slot['realname']}, {age}y").strip()
            interests = [
                d.strip().lower()
                for d in (slot["general_domain"], slot["specific_domain"])
                if d and d.strip()
            ]

        runtime = _derive_runtime_fields(mbti, rng)

        profile = AgentProfile(
            agent_id=i,
            realname=slot["realname"],
            username=slot["username"],
            age=age,
            gender=slot["gender"],
            mbti=mbti,
            country="Vietnam",
            persona=persona_text,
            bio=bio_text,
            original_persona=slot["original_persona"],
            general_domain=slot["general_domain"],
            specific_domain=slot["specific_domain"],
            interests=interests,
            **runtime,
        )
        profiles.append(profile.model_dump())

    return profiles


# ── POST /api/sim/prepare ──
@router.post("/prepare")
async def prepare_simulation(req: PrepareRequest):
    """Prepare simulation: generate profiles + config.
    
    This uses the Core Service's campaign data (via shared uploads dir)
    and generates OASIS-compatible agent profiles.
    """
    # Verify campaign exists tại nested layout
    from ecosim_common.path_resolver import (
        compute_campaign_paths, compute_simulation_paths, ensure_simulation_dirs,
    )
    cpaths = compute_campaign_paths(req.campaign_id)
    spec_path = cpaths["spec_path"]
    if not os.path.exists(spec_path):
        raise HTTPException(
            404,
            f"Campaign {req.campaign_id} chưa upload (spec.json không tồn tại tại {spec_path})",
        )

    # Phase 15.tracking: enforce min 2 agents (tracking 2 agents đầu mặc định).
    if req.num_agents < 2:
        raise HTTPException(
            400,
            f"num_agents tối thiểu là 2 (cognitive tracking track 2 agents). "
            f"Got: {req.num_agents}",
        )

    # Phase 15.tracking: resolve tracked_agent_ids — backward compat với
    # tracked_agent_id (single int). Default [0, 1] nếu cả hai không set.
    tracked_ids: List[int] = list(req.tracked_agent_ids or [])
    if not tracked_ids and req.tracked_agent_id is not None:
        tracked_ids = [int(req.tracked_agent_id)]
    if not tracked_ids:
        tracked_ids = [0, 1]
    # Cap valid ids vào range
    tracked_ids = sorted(set(
        i for i in tracked_ids if 0 <= i < req.num_agents
    ))[:5]  # cap 5 agents max để tránh tracking quá nặng

    # Pre-flight: nếu user yêu cầu Zep content extraction nhưng không có API key
    # → fail fast với gợi ý rõ ràng. None = inherit env (graceful skip).
    if req.enable_zep_runtime is True and not os.environ.get("ZEP_API_KEY"):
        raise HTTPException(
            400,
            "enable_zep_runtime=true nhưng ZEP_API_KEY chưa set trong .env. "
            "Set ZEP_API_KEY hoặc tắt toggle 'Zep content extraction' ở wizard.",
        )

    # Phase 10: clone master KG → sim graph + nested folder layout
    from sim_graph_clone import sim_graph_name, clone_campaign_graph_in_falkor
    import shutil

    sim_id = f"sim_{uuid.uuid4().hex[:8]}"
    spaths = compute_simulation_paths(sim_id, req.campaign_id)
    sim_dir = spaths["sim_dir"]
    ensure_simulation_dirs(sim_id, req.campaign_id)

    kg_graph_name = sim_graph_name(sim_id)
    state = SimState(
        sim_id=sim_id,
        status=SimStatus.PREPARING,
        campaign_id=req.campaign_id,
        num_agents=req.num_agents,
        total_rounds=req.num_rounds,
        output_dir=sim_dir,
        created_at=datetime.now().isoformat(),
        group_id=kg_graph_name,
    )
    _simulations[sim_id] = state

    try:
        # Load campaign context
        with open(spec_path, "r", encoding="utf-8") as f:
            spec = json.load(f)

        # Build campaign context summary for config (simple, for reference)
        campaign_context = (
            f"Campaign: {spec.get('name', '')}. "
            f"Type: {spec.get('campaign_type', '')}. "
            f"Market: {spec.get('market', '')}. "
            f"Timeline: {spec.get('timeline', '')}. "
            f"Summary: {spec.get('summary', '')}"
        )

        # Save campaign context for simulation use
        ctx_path = os.path.join(sim_dir, "campaign_context.txt")
        with open(ctx_path, "w", encoding="utf-8") as f:
            f.write(campaign_context)

        # Save config with full campaign data (Phase 10: tên file = config.json)
        config = {
            "sim_id": sim_id,
            "campaign_id": req.campaign_id,
            "num_agents": req.num_agents,
            "num_rounds": req.num_rounds,
            "group_id": state.group_id,
            "kg_graph_name": kg_graph_name,
            "campaign_context": campaign_context,
            "campaign_name": spec.get("name", ""),
            "campaign_market": spec.get("market", ""),
            "campaign_summary": spec.get("summary", ""),
            "stakeholders": spec.get("stakeholders", []),
            "kpis": spec.get("kpis", []),
            "created_at": state.created_at,
            # Cognitive pipeline toggles. Default True cho 4 features đầu, False
            # cho graph_cognition (cần Phase 15 Zep extract chạy 1-2 round mới có
            # data → round 0 sẽ empty, dễ confuse user nếu default ON).
            "enable_agent_memory": req.cognitive_toggles.get("enable_agent_memory", True),
            "enable_mbti_modifiers": req.cognitive_toggles.get("enable_mbti_modifiers", True),
            "enable_interest_drift": req.cognitive_toggles.get("enable_interest_drift", True),
            "enable_reflection": req.cognitive_toggles.get("enable_reflection", True),
            "enable_graph_cognition": req.cognitive_toggles.get("enable_graph_cognition", False),
            # Phase 15.tracking: list of agent_ids để track. Default [0,1].
            # Legacy single field giữ cho backward compat.
            "tracked_agent_ids": tracked_ids,
            "tracked_agent_id": tracked_ids[0] if tracked_ids else -1,
            # Crisis injection events (scheduled)
            "crisis_events": [e.model_dump() for e in req.crisis_events] if req.crisis_events else [],
            # Per-sim Zep override (None = inherit env ZEP_SIM_RUNTIME)
            "enable_zep_runtime": req.enable_zep_runtime,
        }
        config_path = spaths["config_path"]
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # Generate N agent profiles (async: parquet + Graphiti + LLM) — chạy
        # TRƯỚC clone vì LLM profile gen flaky hơn; rollback rẻ hơn nếu fail.
        profiles_path = spaths["profiles_path"]
        profiles = await _generate_profiles(req.num_agents, spec, seed=req.seed)
        with open(profiles_path, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
        logger.info(f"Generated {len(profiles)} agent profiles to {profiles_path}")

        # Phase 10 fix: upsert_simulation TRƯỚC khi update_sim_kg_status.
        # Update statements vào row chưa tồn tại = no-op silently → kg_status
        # vẫn 'pending' sau clone. Tạo row trước, sau đó update các trạng thái.
        from ecosim_common.metadata_index import (
            upsert_simulation, upsert_agents, update_sim_kg_status,
            update_sim_crisis_status,
        )
        try:
            upsert_simulation(
                sim_id, req.campaign_id,
                status="preparing",
                num_agents=req.num_agents,
                num_rounds=req.num_rounds,
                created_at=state.created_at,
                enable_zep_runtime=req.enable_zep_runtime,
            )
            if profiles:
                upsert_agents(sim_id, profiles)
            # Cache scheduled crisis count so list/overview views can render
            # "1 scheduled" badge from a single SELECT without parsing config.json.
            # crisis_log_path / crisis_pending_path columns were already filled
            # by populate_simulation_paths() inside upsert_simulation().
            update_sim_crisis_status(
                sim_id, crisis_count=len(req.crisis_events or [])
            )
        except Exception as _me:
            logger.warning("Metadata sync (prepare init) fail: %s", _me)

        # Phase 10: clone master KG → sim graph trong FalkorDB
        logger.info(
            "Cloning master KG '%s' → sim graph '%s'...",
            req.campaign_id, kg_graph_name,
        )
        try:
            update_sim_kg_status(sim_id, status="forking")
        except Exception as _me:
            logger.warning("update_sim_kg_status('forking') fail: %s", _me)

        # Phase 15.fix: granular try around clone — RuntimeError có context (Step Xa/b)
        try:
            fork_result = await clone_campaign_graph_in_falkor(req.campaign_id, sim_id)
        except Exception as e:
            logger.exception(
                "Prepare[clone]: clone_campaign_graph_in_falkor(%s, %s) fail",
                req.campaign_id, sim_id,
            )
            raise
        logger.info(
            "Clone complete: %d nodes, %d edges, %d episodes, vector_index=%s, %dms",
            fork_result["node_count"], fork_result["edge_count"],
            fork_result["episode_count"],
            fork_result["vector_index_built"], fork_result["elapsed_ms"],
        )

        # Phase 10: SEED AGENT NODES vào sim graph SAU khi clone xong.
        # (:SimAgent) + [:REPRESENTS]→(:Entity) + Graphiti episodes hybrid search.
        agent_seed_stats = {"agents_seeded": 0, "represents_linked": 0, "episodes_added": 0}
        try:
            from sim_agent_seeder import seed_agents_to_sim_graph
            agent_seed_stats = await seed_agents_to_sim_graph(
                sim_id, profiles, kg_edges=None,
            )
            logger.info(
                "Seeded %d agents vào sim graph %s (represents=%d, episodes=%d)",
                agent_seed_stats["agents_seeded"], kg_graph_name,
                agent_seed_stats["represents_linked"],
                agent_seed_stats["episodes_added"],
            )
        except Exception as _se:
            logger.exception(
                "Prepare[seed]: seed_agents_to_sim_graph fail — sim graph có KG entities "
                "nhưng KHÔNG có agent nodes, sim sẽ hoạt động kém: %s", _se,
            )

        # Re-query graph stats sau seed để count phản ánh agent nodes
        try:
            from sim_graph_clone import graph_stats as _graph_stats
            final_stats = _graph_stats(kg_graph_name)
            update_sim_kg_status(
                sim_id,
                status="ready",
                node_count=final_stats["node_count"],
                edge_count=final_stats["edge_count"],
                episode_count=final_stats["episode_count"],
                set_forked_at=True,
            )
        except Exception as _me:
            logger.exception("Prepare[stats]: update_sim_kg_status('ready') fail: %s", _me)

        # ── Phase 15: Init Zep sim graph + seed agents qua Zep ─────────────
        # Order: create Zep graph → apply ontology → seed agents (extract entities
        # từ profile sections + reroute về SimAgent đã tạo ở seed_agents_to_sim_graph).
        zep_seed_stats: Dict = {"status": "skipped", "reason": "zep_disabled"}
        if (
            os.getenv("ZEP_SIM_RUNTIME", "true").lower() == "true"
            and os.getenv("ZEP_API_KEY")
        ):
            zep_graph_ok = False
            try:
                from sim_zep_section_writer import create_sim_zep_graph
                zep_graph_ok = await create_sim_zep_graph(sim_id, master_cid=req.campaign_id)
                if zep_graph_ok:
                    logger.info(
                        "Phase 15: Zep sim graph initialized for sim_%s", sim_id,
                    )
                else:
                    logger.warning(
                        "Phase 15: Zep sim graph init returned False — "
                        "section dispatch disabled cho sim này",
                    )
            except Exception as e:
                logger.exception("Prepare[zep_init]: Zep sim graph init exception: %s", e)

            # Phase 15.fix: agent seed qua Zep (đối xứng round dispatch).
            # Yêu cầu Zep graph init thành công + có profiles.
            if zep_graph_ok and profiles:
                try:
                    from sim_zep_section_writer import seed_agents_via_zep
                    from ecosim_common.llm_client import LLMClient
                    zep_seed_stats = await seed_agents_via_zep(
                        sim_id=sim_id,
                        profiles=profiles,
                        llm=LLMClient(),
                        master_cid=req.campaign_id,
                        falkor_host=os.getenv("FALKORDB_HOST", "localhost"),
                        falkor_port=int(os.getenv("FALKORDB_PORT", "6379")),
                    )
                    logger.info(
                        "Phase 15 agent seed via Zep: %s | +%d entities +%d edges "
                        "+%d eps | reroute=(out=%d in=%d del=%d)",
                        zep_seed_stats.get("status"),
                        zep_seed_stats.get("entities_added", 0),
                        zep_seed_stats.get("edges_added", 0),
                        zep_seed_stats.get("episodes_added", 0),
                        zep_seed_stats.get("rerouted_out", 0),
                        zep_seed_stats.get("rerouted_in", 0),
                        zep_seed_stats.get("cleaned_zep_agents", 0),
                    )
                except Exception as e:
                    logger.exception(
                        "Prepare[zep_seed]: seed_agents_via_zep fail — "
                        "SimAgent anchors đã có (Cypher) nhưng thiếu semantic enrichment: %s", e,
                    )

        # Final: mark sim as 'ready' (top-level status — kg_status đã 'ready' qua step trên)
        state.status = SimStatus.READY
        try:
            from ecosim_common.metadata_index import update_sim_status
            update_sim_status(sim_id, "ready")
        except Exception as _me:
            logger.warning("update_sim_status('ready') fail: %s", _me)

        return {
            "sim_id": sim_id,
            "status": "ready",
            "group_id": state.group_id,
            "kg_graph_name": kg_graph_name,
            "kg_fork_stats": fork_result,
            "output_dir": sim_dir,
            "config_path": config_path,
            "num_agents": req.num_agents,
            "num_rounds": req.num_rounds,
        }

    except ValueError as e:
        # Master KG missing or embedding mismatch → 400
        logger.warning("Sim prepare ValueError for %s: %s", sim_id, e)
        state.status = SimStatus.FAILED
        state.error = str(e)
        shutil.rmtree(sim_dir, ignore_errors=True)
        with _state_lock:
            _simulations.pop(sim_id, None)
            _processes.pop(sim_id, None)
        try:
            from ecosim_common.metadata_index import update_sim_kg_status, delete_simulation
            update_sim_kg_status(sim_id, status="error")
            delete_simulation(sim_id)
        except Exception:
            pass
        raise HTTPException(400, str(e))
    except Exception as e:
        # Phase 15 fix: log full traceback trước raise để debug 500 errors
        logger.exception(
            "Sim prepare 500 for sim_id=%s campaign=%s: %s",
            sim_id, req.campaign_id, e,
        )
        state.status = SimStatus.FAILED
        state.error = str(e)
        shutil.rmtree(sim_dir, ignore_errors=True)
        try:
            from sim_graph_clone import drop_sim_graph
            drop_sim_graph(sim_id)
        except Exception:
            pass
        try:
            from ecosim_common.metadata_index import delete_simulation
            delete_simulation(sim_id)
        except Exception:
            pass
        with _state_lock:
            _simulations.pop(sim_id, None)
            _processes.pop(sim_id, None)
        raise HTTPException(500, f"{type(e).__name__}: {e}")


# ── POST /api/sim/start ──
@router.post("/start")
async def start_simulation(req: StartRequest):
    """Start OASIS simulation as subprocess.

    Phase 12 #2: lock-protected against concurrent /start cho cùng sim_id.
    Trước fix: 2 requests đồng thời → race kill nhầm process.
    """
    state = _get_or_load_state(req.sim_id)
    if not state:
        raise HTTPException(404, f"Simulation {req.sim_id} not found")

    if state.status not in (SimStatus.READY, SimStatus.COMPLETED, SimStatus.FAILED, SimStatus.RUNNING):
        raise HTTPException(400, f"Simulation must be READY, current: {state.status}")

    group_id = req.group_id or state.group_id or req.sim_id

    # Phase 12 #2: atomic kill-old + reserve slot trong lock
    with _state_lock:
        old_proc = _processes.get(req.sim_id)
        if old_proc and old_proc.poll() is None:
            logger.info(f"Killing previous simulation process {old_proc.pid}")
            try:
                old_proc.kill()
                old_proc.wait(timeout=5)
            except Exception as _ke:
                logger.warning("kill old proc failed: %s", _ke)
        _processes.pop(req.sim_id, None)
    
    # Build subprocess command
    run_script = os.path.join(SCRIPT_DIR, "run_simulation.py")
    cmd = [OASIS_VENV_PYTHON, run_script, "--group-id", group_id, "--sim-dir", state.output_dir]
    
    logger.info(f"Starting simulation: {cmd}")
    
    # Set PYTHONIOENCODING to avoid cp1252 errors on Windows
    sub_env = os.environ.copy()
    sub_env["PYTHONIOENCODING"] = "utf-8"

    # Override ZEP_SIM_RUNTIME per-sim (từ enable_zep_runtime trong config).
    # None → inherit env default. True/False → explicit override.
    try:
        cfg_path = os.path.join(state.output_dir, "simulation_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                _cfg = json.load(f)
            _zep_override = _cfg.get("enable_zep_runtime")
            if _zep_override is True:
                sub_env["ZEP_SIM_RUNTIME"] = "true"
            elif _zep_override is False:
                sub_env["ZEP_SIM_RUNTIME"] = "false"
    except Exception as _e:
        logger.warning("Failed to read enable_zep_runtime override: %s", _e)
    
    try:
        # Pipe stdout to log file AND print to console
        log_path = os.path.join(state.output_dir, "simulation.log")
        log_file = open(log_path, "w", encoding="utf-8")
        
        proc = subprocess.Popen(
            cmd,
            cwd=SCRIPT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=sub_env,
        )
        with _state_lock:
            _processes[req.sim_id] = proc
            _simulations[req.sim_id] = state  # ensure cached
        state.status = SimStatus.RUNNING
        state.group_id = group_id

        # Phase 5: sync metadata index — sim started
        try:
            from ecosim_common.metadata_index import update_sim_status
            update_sim_status(
                req.sim_id, "running",
                started_at=datetime.now().isoformat(),
            )
        except Exception as _me:
            logger.warning("Metadata sync (start) fail: %s", _me)
        
        # Background thread: read stdout, write to log + print to console
        def _monitor():
            try:
                for line in proc.stdout:
                    line_stripped = line.rstrip()
                    if line_stripped:
                        log_file.write(line)
                        log_file.flush()
                        # Print to sim service console
                        logger.info(f"[{req.sim_id}] {line_stripped}")
            except Exception:
                pass
            finally:
                proc.wait()
                log_file.close()
                # Read final status from progress.json
                progress_path = os.path.join(state.output_dir, "progress.json")
                if os.path.exists(progress_path):
                    try:
                        with open(progress_path, "r") as f:
                            prog = json.load(f)
                        if prog.get("status") == "completed":
                            state.status = SimStatus.COMPLETED
                        else:
                            state.status = SimStatus.COMPLETED if proc.returncode in (0, 1) else SimStatus.FAILED
                        state.current_round = prog.get("current_round", 0)
                        state.total_rounds = prog.get("total_rounds", state.total_rounds)
                    except Exception:
                        state.status = SimStatus.COMPLETED if proc.returncode in (0, 1) else SimStatus.FAILED
                else:
                    state.status = SimStatus.COMPLETED if proc.returncode in (0, 1) else SimStatus.FAILED
                logger.info(f"Simulation {req.sim_id} finished: exit={proc.returncode}, status={state.status}")

                # Phase 5: sync metadata index — sim finished
                try:
                    from ecosim_common.metadata_index import update_sim_status
                    update_sim_status(
                        req.sim_id,
                        state.status.value,
                        current_round=state.current_round,
                        completed_at=datetime.now().isoformat(),
                    )
                except Exception as _me:
                    logger.warning("Metadata sync (complete) fail: %s", _me)

                # Phase 15: Zep finalize (Node 11-12 build indices + delete Zep
                # graph) đã chạy inline trong run_simulation.py sau round loop.
                # API layer chỉ sync meta.db status.

                # Phase 10: query final FalkorDB stats + sync meta.db kg_status
                # (no JSON snapshot persist — FalkorDB là source of truth).
                if state.status == SimStatus.COMPLETED:
                    try:
                        from sim_graph_clone import sim_graph_name, graph_stats
                        from ecosim_common.metadata_index import update_sim_kg_status
                        gname = sim_graph_name(req.sim_id)
                        stats = graph_stats(gname)
                        update_sim_kg_status(
                            req.sim_id,
                            status="completed",
                            node_count=stats["node_count"],
                            edge_count=stats["edge_count"],
                            episode_count=stats["episode_count"],
                        )
                        logger.info(
                            "Sim %s kg_status='completed' synced: %s", req.sim_id, stats,
                        )
                    except Exception as e:
                        logger.warning(
                            "Sim final kg sync failed for %s: %s", req.sim_id, e,
                        )

        threading.Thread(target=_monitor, daemon=True).start()
        
        return {
            "sim_id": req.sim_id,
            "status": "running",
            "group_id": group_id,
            "pid": proc.pid,
        }
        
    except Exception as e:
        state.status = SimStatus.FAILED
        state.error = str(e)
        raise HTTPException(500, str(e))


# ── GET /api/sim/status ──
@router.get("/status")
async def get_status(sim_id: str = Query(...)):
    """Get simulation status — Phase 12 #2: meta.db single source of truth."""
    state = _get_or_load_state(sim_id)
    if not state:
        raise HTTPException(404, f"Simulation {sim_id} not found")
    return state.model_dump()


# ── GET /api/sim/list ──
@router.get("/list")
async def list_simulations(campaign_id: Optional[str] = Query(None)):
    """List simulations, optionally filtered by campaign_id.

    Phase 5: query SQLite metadata index thay vì walk filesystem mỗi request.
    Fallback to in-memory state nếu DB không sẵn sàng.
    """
    try:
        from ecosim_common.metadata_index import list_simulations as db_list
        rows = db_list(cid=campaign_id)
        # Map DB schema → response schema (frontend expects `campaign_id` not `cid`)
        sims = [
            {
                "sim_id": r["sid"],
                "campaign_id": r["cid"],
                "group_id": r["sid"],  # FalkorDB graph name = sim_id
                "status": r["status"],
                "num_agents": r["num_agents"],
                "num_rounds": r["num_rounds"],
                "current_round": r["current_round"],
                "created_at": r["created_at"],
                "started_at": r.get("started_at"),
                "completed_at": r.get("completed_at"),
            }
            for r in rows
        ]
        return {"simulations": sims, "count": len(sims), "campaign_id": campaign_id}
    except Exception as _e:
        logger.warning("DB list fallback to filesystem scan: %s", _e)
        _scan_disk()
        sims = [s.model_dump() for s in _simulations.values()]
        if campaign_id:
            sims = [s for s in sims if s.get("campaign_id") == campaign_id]
        return {"simulations": sims, "count": len(sims), "campaign_id": campaign_id}


# ── DELETE /api/sim/{sim_id} ──
@router.delete("/{sim_id}")
async def delete_simulation(sim_id: str):
    """Cascade delete 1 sim: kill subprocess → drop sim graph → rmtree sim_dir
    → remove khỏi campaign manifest → pop in-memory state.

    Idempotent: gọi 2 lần không error. Trả 404 nếu sim không tồn tại trên disk.
    """
    import shutil
    from sim_graph_clone import drop_sim_graph
    from ecosim_common.metadata_index import get_simulation, delete_simulation

    state = _get_or_load_state(sim_id)  # Phase 12 #2
    sim_dir = None
    if state:
        sim_dir = state.output_dir
    else:
        try:
            from ecosim_common.path_resolver import resolve_simulation_paths
            sim_dir = resolve_simulation_paths(sim_id).get("sim_dir")
        except Exception:
            sim_dir = None

    sim_exists_on_disk = bool(sim_dir and os.path.isdir(sim_dir))
    db_row = get_simulation(sim_id)
    if not sim_exists_on_disk and not state and not db_row:
        raise HTTPException(404, f"Simulation {sim_id} not found")

    # 1. Kill subprocess nếu còn chạy
    if state and getattr(state, "process", None):
        try:
            proc = state.process
            if proc and proc.poll() is None:
                proc.terminate()
                logger.info("Killed subprocess for sim %s", sim_id)
        except Exception as e:
            logger.warning("Failed to kill subprocess for %s: %s", sim_id, e)

    # 2. Drop FalkorDB sim graph
    graph_dropped = False
    try:
        graph_dropped = drop_sim_graph(sim_id)
    except Exception as e:
        logger.warning("drop_sim_graph(%s) failed: %s", sim_id, e)

    # 3. Remove sim_dir
    dir_removed = False
    if os.path.isdir(sim_dir):
        shutil.rmtree(sim_dir, ignore_errors=True)
        dir_removed = True

    # 4. Remove from meta.db (Phase 10: source of truth for sim ↔ campaign mapping)
    manifest_removed = False
    try:
        delete_simulation(sim_id)
        manifest_removed = True
    except Exception as e:
        logger.warning("meta.db delete_simulation(%s) failed: %s", sim_id, e)

    # 5. Drop in-memory state (Phase 12 #2: locked)
    with _state_lock:
        _simulations.pop(sim_id, None)
        _processes.pop(sim_id, None)

    return {
        "sim_id": sim_id,
        "deleted": True,
        "graph_dropped": graph_dropped,
        "dir_removed": dir_removed,
        "manifest_removed": manifest_removed,
        "campaign_id": (
            (state.campaign_id if state else None)
            or (db_row.get("cid") if db_row else None)
        ),
    }


# ── GET /api/sim/{sim_id}/profiles ──
@router.get("/{sim_id}/profiles")
async def get_profiles(sim_id: str):
    """Get agent profiles for a simulation. Path resolved via meta.db."""
    json_path = _sim_paths(sim_id).get("profiles_path") or ""
    if json_path and os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            profiles = json.load(f)
        return {"profiles": profiles, "count": len(profiles)}
    raise HTTPException(404, f"Profiles not found at {json_path}")


# ── GET /api/sim/{sim_id}/feed ──
@router.get("/{sim_id}/feed")
async def get_sim_feed(sim_id: str, limit: int = 100):
    """Social media feed: posts + comments + likes từ OASIS oasis.db (SQLite)."""
    try:
        return await _get_sim_feed_impl(sim_id, limit)
    except Exception as e:
        logger.exception("get_sim_feed failed for %s", sim_id)
        return {"sim_id": sim_id, "posts": [], "count": 0, "error": f"{type(e).__name__}: {e}"}


async def _get_sim_feed_impl(sim_id: str, limit: int):
    import sqlite3 as _sqlite

    # Resolve OASIS SQLite path via meta.db. Old code probed both `oasis.db`
    # and `oasis_simulation.db` because the column name was wrong; v5
    # migration fixed the column to point at the actual filename.
    db_path = _sim_paths(sim_id).get("oasis_db_path") or ""

    if not db_path or not os.path.exists(db_path):
        return {"sim_id": sim_id, "posts": [], "count": 0,
                "error": f"oasis.db not found"}

    # Load profiles để map user_id → name + mbti
    profiles_by_uid: Dict[int, Dict[str, Any]] = {}
    try:
        from ecosim_common.path_resolver import resolve_simulation_paths
        prof_path = resolve_simulation_paths(sim_id).get("profiles_path") or ""
        if prof_path and os.path.exists(prof_path):
            with open(prof_path, "r", encoding="utf-8") as f:
                profs = json.load(f)
            # OASIS user_id = agent_id + 1 (1-indexed). Profiles[i].agent_id = i (0-indexed).
            for p in profs:
                aid = int(p.get("agent_id", 0))
                profiles_by_uid[aid + 1] = {
                    "agent_id": aid,
                    "name": p.get("realname") or p.get("name") or f"Agent#{aid}",
                    "mbti": p.get("mbti", ""),
                }
    except Exception as _pe:
        logger.debug("load profiles fail: %s", _pe)

    def _author_dict(user_id: int) -> Dict[str, Any]:
        prof = profiles_by_uid.get(user_id, {})
        return {
            "agent_id": prof.get("agent_id", user_id - 1),
            "name": prof.get("name") or f"Agent#{user_id - 1}",
            "mbti": prof.get("mbti", ""),
        }

    posts: List[Dict[str, Any]] = []
    try:
        conn = _sqlite.connect(db_path)
        conn.row_factory = _sqlite.Row
        cur = conn.cursor()

        # Posts (newest first). Filter content '' (seed posts often empty).
        cur.execute(
            "SELECT post_id, user_id, content, created_at, num_likes, num_dislikes, "
            "       num_shares, original_post_id "
            "FROM post ORDER BY post_id DESC LIMIT ?",
            (int(limit),),
        )
        post_rows = cur.fetchall()
        post_ids = [r["post_id"] for r in post_rows]

        # Likes per post
        likes_by_post: Dict[int, List[Dict[str, Any]]] = {}
        if post_ids:
            placeholders = ",".join("?" * len(post_ids))
            cur.execute(
                f"SELECT post_id, user_id, created_at FROM like "
                f"WHERE post_id IN ({placeholders}) ORDER BY created_at",
                post_ids,
            )
            for r in cur.fetchall():
                pid = r["post_id"]
                likes_by_post.setdefault(pid, []).append({
                    "agent_id": _author_dict(r["user_id"])["agent_id"],
                    "name": _author_dict(r["user_id"])["name"],
                    "created_at": r["created_at"],
                })

        # Comments per post
        comments_by_post: Dict[int, List[Dict[str, Any]]] = {}
        if post_ids:
            placeholders = ",".join("?" * len(post_ids))
            cur.execute(
                f"SELECT comment_id, post_id, user_id, content, created_at, "
                f"       num_likes, num_dislikes "
                f"FROM comment WHERE post_id IN ({placeholders}) "
                f"ORDER BY post_id, comment_id",
                post_ids,
            )
            for r in cur.fetchall():
                pid = r["post_id"]
                comments_by_post.setdefault(pid, []).append({
                    "comment_id": r["comment_id"],
                    "content": r["content"] or "",
                    "created_at": r["created_at"],
                    "num_likes": r["num_likes"] or 0,
                    "num_dislikes": r["num_dislikes"] or 0,
                    "author": _author_dict(r["user_id"]),
                })

        for r in post_rows:
            pid = r["post_id"]
            content = r["content"] or ""
            # Skip empty seed posts (OASIS init creates 0-content rows)
            if not content.strip():
                continue
            likes = likes_by_post.get(pid, [])
            comments = comments_by_post.get(pid, [])
            posts.append({
                "post_id": pid,
                "content": content,
                "created_at": r["created_at"],
                "original_post_id": r["original_post_id"],
                "author": _author_dict(r["user_id"]),
                "likes_count": int(r["num_likes"] or 0) or len(likes),
                "dislikes_count": int(r["num_dislikes"] or 0),
                "shares_count": int(r["num_shares"] or 0),
                "likes": likes,
                "comments_count": len(comments),
                "comments": comments,
            })

        conn.close()
    except Exception as e:
        logger.warning("feed sqlite query fail for %s: %s", sim_id, e)
        return {"sim_id": sim_id, "posts": [], "count": 0, "error": str(e)}

    return {"sim_id": sim_id, "posts": posts, "count": len(posts)}


# ── GET /api/sim/{sim_id}/config ──
@router.get("/{sim_id}/config")
async def get_config(sim_id: str):
    """Get simulation config (path resolved via meta.db)."""
    config_path = _sim_paths(sim_id).get("config_path") or ""
    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    raise HTTPException(404, "Config not found")


# ── GET /api/sim/{sim_id}/actions ──
@router.get("/{sim_id}/actions")
async def get_actions(sim_id: str):
    """Get simulation actions from actions.jsonl (path via meta.db)."""
    actions_path = _sim_paths(sim_id).get("actions_path") or ""
    if not actions_path or not os.path.exists(actions_path):
        # Return empty list instead of 404 while simulation is still running
        return {"actions": [], "count": 0}

    actions = []
    with open(actions_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    actions.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    return {"actions": actions, "count": len(actions)}


# ── GET /api/sim/{sim_id}/progress ──
@router.get("/{sim_id}/progress")
async def get_progress(sim_id: str):
    """Get simulation progress from progress.json file."""
    state = _simulations.get(sim_id)
    if not state:
        # Try disk-based recovery (service may have restarted)
        _scan_disk()
        state = _simulations.get(sim_id)
    if not state:
        raise HTTPException(404, f"Simulation {sim_id} not found")
    
    # Check process
    proc = _processes.get(sim_id)
    is_running = proc and proc.poll() is None
    
    # Read progress from file written by subprocess
    current_round = state.current_round
    total_rounds = state.total_rounds
    file_status = state.status
    
    progress_path = _sim_paths(sim_id).get("progress_path") or ""
    if progress_path and os.path.exists(progress_path):
        try:
            with open(progress_path, "r") as f:
                prog = json.load(f)
            current_round = prog.get("current_round", current_round)
            total_rounds = prog.get("total_rounds", total_rounds)
            file_status = prog.get("status", file_status)
            # Sync back to in-memory state
            state.current_round = current_round
            state.total_rounds = total_rounds
            if file_status == "completed" and state.status == SimStatus.RUNNING:
                state.status = SimStatus.COMPLETED
        except Exception:
            pass

    return {
        "sim_id": sim_id,
        "status": state.status,
        "current_round": current_round,
        "total_rounds": total_rounds,
        "is_running": is_running,
        "group_id": state.group_id,
    }


# ── GET /api/sim/{sim_id}/stream ── (SSE)
@router.get("/{sim_id}/stream")
async def stream_simulation(sim_id: str):
    """SSE endpoint: streams real-time progress and actions after each round."""
    state = _simulations.get(sim_id)
    if not state:
        _scan_disk()
        state = _simulations.get(sim_id)
    if not state:
        raise HTTPException(404, f"Simulation {sim_id} not found")
    
    # Resolve file paths once (not per-tick) — meta.db row doesn't move.
    paths = _sim_paths(sim_id)
    progress_path = paths.get("progress_path") or ""
    actions_path = paths.get("actions_path") or ""
    log_path = paths.get("simulation_log_path") or ""

    async def event_generator():
        last_round = -1
        last_action_count = 0

        while True:
            # Read progress from file
            current_round = 0
            total_rounds = state.total_rounds
            file_status = "waiting"

            if progress_path and os.path.exists(progress_path):
                try:
                    with open(progress_path, "r") as f:
                        prog = json.load(f)
                    current_round = prog.get("current_round", 0)
                    total_rounds = prog.get("total_rounds", total_rounds)
                    file_status = prog.get("status", "waiting")
                except Exception:
                    pass

            # Send progress update when round changes
            if current_round != last_round:
                last_round = current_round
                progress_data = json.dumps({
                    "current_round": current_round,
                    "total_rounds": total_rounds,
                    "status": file_status,
                })
                yield f"event: progress\ndata: {progress_data}\n\n"

                # Also send new actions
                if actions_path and os.path.exists(actions_path):
                    try:
                        with open(actions_path, "r", encoding="utf-8") as f:
                            all_actions = []
                            for line in f:
                                line = line.strip()
                                if line:
                                    try:
                                        all_actions.append(json.loads(line))
                                    except json.JSONDecodeError:
                                        pass

                        # Send only new actions since last batch
                        new_actions = all_actions[last_action_count:]
                        last_action_count = len(all_actions)

                        if new_actions:
                            actions_data = json.dumps({
                                "round": current_round,
                                "new_actions": new_actions,
                                "total_actions": len(all_actions),
                            })
                            yield f"event: actions\ndata: {actions_data}\n\n"
                    except Exception:
                        pass

            # Send log lines if available
            if log_path and os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    # Send last 5 log lines as a heartbeat/log event
                    recent = [l.rstrip() for l in lines[-5:] if l.strip()]
                    if recent:
                        log_data = json.dumps({"lines": recent})
                        yield f"event: log\ndata: {log_data}\n\n"
                except Exception:
                    pass
            
            # Check if simulation is done
            if file_status in ("completed", "failed"):
                done_data = json.dumps({"status": file_status, "total_rounds": total_rounds})
                yield f"event: done\ndata: {done_data}\n\n"
                break
            
            # Check if process died without updating progress
            proc = _processes.get(sim_id)
            if proc and proc.poll() is not None and file_status != "completed":
                yield f"event: done\ndata: {{\"status\": \"failed\", \"error\": \"Process exited\"}}\n\n"
                break
            
            await asyncio.sleep(3)  # Check every 3 seconds
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



# ── Helpers ──
def _scan_disk():
    """Phase 10: rebuild `_simulations` in-memory dict từ meta.db + filesystem.

    Source of truth = meta.db. Filesystem cung cấp progress.json để override
    status/current_round nếu sim đang/đã chạy.
    """
    try:
        from ecosim_common.metadata_index import list_simulations as db_list
        from ecosim_common.path_resolver import resolve_simulation_paths
    except Exception as e:
        logger.warning("_scan_disk: meta.db không sẵn sàng: %s", e)
        return

    try:
        rows = db_list()
    except Exception as e:
        logger.warning("_scan_disk: list_simulations fail: %s", e)
        return

    for r in rows:
        sid = r.get("sid")
        if not sid or sid in _simulations:
            continue
        try:
            paths = resolve_simulation_paths(sid)
            sim_dir = paths.get("sim_dir") or ""
            cid = r.get("cid", "")

            # Map DB status → SimStatus enum
            status_str = (r.get("status") or "created").lower()
            try:
                status = SimStatus(status_str)
            except Exception:
                status = SimStatus.READY

            current_round = int(r.get("current_round", 0) or 0)
            total_rounds = int(r.get("num_rounds", 0) or 0)

            # Override từ progress.json nếu có (sim đã/đang chạy)
            progress_path = paths.get("progress_path") or os.path.join(sim_dir, "progress.json")
            if progress_path and os.path.exists(progress_path):
                try:
                    with open(progress_path, "r", encoding="utf-8") as pf:
                        prog = json.load(pf)
                    current_round = int(prog.get("current_round", current_round))
                    total_rounds = int(prog.get("total_rounds", total_rounds))
                    pstatus = prog.get("status", "")
                    if pstatus == "completed":
                        status = SimStatus.COMPLETED
                    elif pstatus == "running" and status != SimStatus.RUNNING:
                        # Process gone nhưng progress chưa "completed" → coi như completed
                        status = SimStatus.COMPLETED
                except Exception:
                    pass

            kg_graph_name = sid if sid.startswith("sim_") else f"sim_{sid}"
            _simulations[sid] = SimState(
                sim_id=sid,
                status=status,
                campaign_id=cid,
                num_agents=int(r.get("num_agents", 0) or 0),
                total_rounds=total_rounds,
                current_round=current_round,
                output_dir=sim_dir,
                created_at=r.get("created_at", "") or "",
                group_id=kg_graph_name,
            )
        except Exception as e:
            logger.debug("_scan_disk skip sim %s: %s", sid, e)


# ── POST /api/sim/{sim_id}/inject-crisis ──
@router.post("/{sim_id}/inject-crisis")
async def inject_crisis(sim_id: str, event: CrisisEventDef):
    """Inject a crisis event into a running simulation (real-time).
    
    Uses file-based IPC: writes pending_crisis.json which the
    simulation subprocess picks up at the start of the next round.
    """
    state = _simulations.get(sim_id)
    if not state:
        _scan_disk()
        state = _simulations.get(sim_id)
    if not state:
        raise HTTPException(404, f"Simulation {sim_id} not found")
    
    # Write pending crisis file for subprocess to pick up — path from meta.db
    pending_path = (
        _sim_paths(sim_id).get("crisis_pending_path")
        or os.path.join(state.output_dir, "pending_crisis.json")
    )
    
    # Support multiple pending events (append to existing file)
    existing = []
    if os.path.exists(pending_path):
        try:
            with open(pending_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                existing = [existing]
        except Exception:
            existing = []
    
    existing.append(event.model_dump())
    
    try:
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Crisis injected for {sim_id}: {event.title} (type={event.crisis_type})")
        
        return {
            "status": "injected",
            "sim_id": sim_id,
            "crisis_type": event.crisis_type,
            "title": event.title,
            "message": "Crisis event queued. Will be processed at the start of the next round.",
            "pending_count": len(existing),
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to write crisis event: {e}")


# ── POST /api/sim/{sim_id}/evict — Phase 10: WARNING destructive ──
# Phase 10 dropped /restore-kg endpoint (no JSON snapshot to restore from).
# Evict giờ là DESTRUCTIVE: drop sim graph khỏi FalkorDB → mất hoàn toàn,
# không restore lại được. Caller phải re-prepare sim mới (clone master + re-seed).
@router.post("/{sim_id}/evict")
async def evict_sim_graph(sim_id: str):
    """Drop sim graph khỏi FalkorDB. DESTRUCTIVE — mất permanent."""
    if not sim_id:
        raise HTTPException(400, "sim_id required")

    from sim_graph_clone import sim_graph_name, drop_sim_graph
    graph_name = sim_graph_name(sim_id)

    evicted = False
    try:
        evicted = drop_sim_graph(sim_id)
    except Exception as e:
        logger.warning("drop_sim_graph(%s) failed: %s", sim_id, e)

    # Sync meta.db kg_status → 'error' (graph gone, can't query)
    try:
        from ecosim_common.metadata_index import update_sim_kg_status
        update_sim_kg_status(sim_id, status="error")
    except Exception:
        pass

    return {
        "sim_id": sim_id,
        "evicted": evicted,
        "falkor_graph": graph_name,
        "note": "Phase 10: sim graph DESTROYED. Re-prepare sim để có lại.",
    }


# Phase 15: /replay-zep-buffer endpoint removed. Phase 15 không có jsonl
# buffer (sections submit ngay end-of-round, không persist disk). Nếu round
# Zep submit fail → log warning, round sau vẫn tiếp tục bình thường.


# ── GET /api/sim/zep-orphans (Phase E.3 admin) ──
@router.get("/zep-orphans")
async def list_zep_orphans():
    """List sim_* graphs trên Zep server không khớp với sim hiện tại trên disk.

    Trigger sau khi sim đã xong, nếu Phase 15 finalize fail không delete được
    Zep graph → orphan tích lũy. Endpoint này list để admin biết + delete tay
    qua DELETE /api/sim/zep-orphans/{graph_id}.

    Yêu cầu: ZEP_API_KEY set.
    """
    if not os.getenv("ZEP_API_KEY"):
        raise HTTPException(503, "ZEP_API_KEY missing")
    try:
        from ecosim_common.zep_client import make_async_zep_client
        zep = make_async_zep_client()
        all_graphs = await zep.graph.list_all(limit=200)

        # Filter sim_* graphs
        zep_sim_graphs = [
            g.graph_id for g in (getattr(all_graphs, "graphs", []) or [])
            if g.graph_id.startswith("sim_")
        ]

        # Active sims trong service state
        active_sim_graphs = {
            f"sim_{sid[4:] if sid.startswith('sim_') else sid}"
            for sid in _simulations.keys()
        }

        orphans = sorted(set(zep_sim_graphs) - active_sim_graphs)
        return {
            "zep_sim_graphs_total": len(zep_sim_graphs),
            "active_sim_graphs": sorted(active_sim_graphs),
            "orphans": orphans,
            "orphan_count": len(orphans),
        }
    except Exception as e:
        logger.exception("list_zep_orphans failed")
        raise HTTPException(500, f"list error: {e}")


@router.delete("/zep-orphans/{graph_id}")
async def delete_zep_orphan(graph_id: str):
    """Delete 1 orphan Zep graph (free quota).

    Safety: chỉ accept graph_id starting with 'sim_'. Master KG graphs
    (campaign_id) KHÔNG xóa qua endpoint này — phải dùng admin riêng.
    """
    if not graph_id or not graph_id.startswith("sim_"):
        raise HTTPException(400, "graph_id phải bắt đầu bằng 'sim_'")
    if not os.getenv("ZEP_API_KEY"):
        raise HTTPException(503, "ZEP_API_KEY missing")
    try:
        from ecosim_common.zep_client import make_async_zep_client
        zep = make_async_zep_client()
        await zep.graph.delete(graph_id=graph_id)
        return {"status": "deleted", "graph_id": graph_id}
    except Exception as e:
        logger.exception("delete_zep_orphan failed for %s", graph_id)
        raise HTTPException(500, f"delete error: {e}")


# ── GET /api/sim/{sim_id}/crisis-log ──
@router.get("/{sim_id}/crisis-log")
async def get_crisis_log(sim_id: str):
    """Return triggered-crisis log + cached counts.

    meta.db is the source of truth for both the file path and the cached
    counts (set by /prepare and updated by run_simulation each round). We
    resolve `crisis_log_path` from meta.db here instead of recomputing the
    convention path, so list views or dashboards relying on the same row
    stay coherent with what's actually on disk.
    """
    log: list = []
    crisis_count = 0
    triggered_count = 0
    try:
        from ecosim_common.metadata_index import get_simulation
        from ecosim_common.path_resolver import resolve_simulation_paths
        meta = get_simulation(sim_id) or {}
        crisis_count = int(meta.get("crisis_count") or 0)
        triggered_count = int(meta.get("crisis_triggered_count") or 0)
        paths = resolve_simulation_paths(sim_id, fallback=True)
        log_path = paths.get("crisis_log_path") or ""
    except Exception as e:
        logger.debug("crisis-log: meta.db lookup fail (%s), falling back to convention", e)
        state = _simulations.get(sim_id)
        sim_dir = state.output_dir if state else os.path.join(SIM_DIR, sim_id)
        log_path = os.path.join(sim_dir, "crisis_log.json")

    if log_path and os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                log = json.load(f) or []
        except Exception:
            log = []

    # Self-heal: if the file has entries but the cached counter on the
    # meta.db row is lower (e.g. sim crashed between writing crisis_log.json
    # and calling update_sim_crisis_status, or a legacy sim ran before the
    # counter column existed), trust the file. Also write back the corrected
    # value so next read is cheap.
    if isinstance(log, list) and len(log) > triggered_count:
        triggered_count = len(log)
        try:
            from ecosim_common.metadata_index import update_sim_crisis_status
            update_sim_crisis_status(sim_id, triggered_count=triggered_count)
        except Exception as e:
            logger.debug("crisis-log self-heal write fail: %s", e)

    # Merge with the scheduled `crisis_events` from config.json so the UI
    # can render the full original payload (description, affected_domains,
    # interest_keywords, persist_rounds, intensity_decay) — not just the
    # slim triggered_log entries (which only carry id/round/title/type/sev).
    scheduled: list = []
    try:
        cfg_path = _sim_paths(sim_id).get("config_path") or ""
        if cfg_path and os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            scheduled = list(cfg.get("crisis_events") or [])
    except Exception as e:
        logger.debug("crisis-log: scheduled load fail: %s", e)

    # Build the merged response — one entry per scheduled crisis, augmented
    # with the trigger record if it actually fired. Preserves original order
    # so UI can render in sched. Match by `(trigger_round, title)` since
    # crisis_id only lives on the engine's runtime objects.
    triggered_index: dict = {}
    for item in log if isinstance(log, list) else []:
        if not isinstance(item, dict):
            continue
        # Most-recent trigger wins if duplicate (shouldn't happen)
        triggered_index[(int(item.get("round", -1)), item.get("title", ""))] = item

    crises: list = []
    for sch in scheduled:
        if not isinstance(sch, dict):
            continue
        key = (int(sch.get("trigger_round", -1)), sch.get("title", ""))
        trig = triggered_index.get(key)
        crises.append({
            # Scheduled definition (full UI payload)
            "trigger_round": int(sch.get("trigger_round", 0)),
            "title": sch.get("title", ""),
            "description": sch.get("description", ""),
            "crisis_type": sch.get("crisis_type", "custom"),
            "severity": float(sch.get("severity", 0.5)),
            "sentiment_shift": sch.get("sentiment_shift", "negative"),
            "affected_domains": list(sch.get("affected_domains") or []),
            "interest_keywords": list(sch.get("interest_keywords") or []),
            "persist_rounds": int(sch.get("persist_rounds", 3)),
            "intensity_decay": float(sch.get("intensity_decay", 0.5)),
            # Trigger status — None until it fires
            "triggered": trig is not None,
            "triggered_round": int(trig["round"]) if trig else None,
            "crisis_id": (trig.get("crisis_id") if trig else None),
        })

    # If config.json has nothing but the log does (legacy sim from before
    # crisis_events was persisted in config), fall back to log-only entries.
    if not crises and isinstance(log, list):
        for item in log:
            if not isinstance(item, dict):
                continue
            crises.append({
                "trigger_round": int(item.get("round", 0)),
                "title": item.get("title", ""),
                "description": "",
                "crisis_type": item.get("type", "custom"),
                "severity": float(item.get("severity", 0.5)),
                "sentiment_shift": "negative",
                "affected_domains": [],
                "interest_keywords": [],
                "persist_rounds": 3,
                "intensity_decay": 0.5,
                "triggered": True,
                "triggered_round": int(item.get("round", 0)),
                "crisis_id": item.get("crisis_id"),
            })

    return {
        # New full payload — UI should consume this
        "crises": crises,
        # Backward-compatible slim log (list of triggered entries)
        "crisis_log": log,
        "crisis_count": crisis_count,
        "crisis_triggered_count": triggered_count,
    }


# ══════════════════════════════════════════════════════════════════
# COGNITIVE TRACKING: Parse agent_tracking.txt into structured JSON
# ══════════════════════════════════════════════════════════════════

import re as _re

def _parse_tracking_file(tracking_path: str) -> dict:
    """Parse agent_tracking.txt into structured JSON data."""
    with open(tracking_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse header
    header_match = _re.search(r"Agent: (.+?) \(ID=(\d+)\)", content)
    mbti_match = _re.search(r"MBTI: (\w+)", content)
    agent_info = {
        "name": header_match.group(1) if header_match else "Unknown",
        "id": int(header_match.group(2)) if header_match else 0,
        "mbti": mbti_match.group(1) if mbti_match else "",
    }

    # Split by round sections
    round_blocks = _re.split(r"={60,}\s*\n\s*ROUND", content)
    rounds = []

    for block in round_blocks[1:]:  # Skip header block
        rd = {}
        # Round number
        round_match = _re.match(r"\s*(\d+)", block)
        rd["round"] = int(round_match.group(1)) if round_match else 0

        # Base Persona
        bp_match = _re.search(r"\[BASE PERSONA\]\s*\n(.*?)(?=\n\[)", block, _re.DOTALL)
        rd["base_persona"] = bp_match.group(1).strip() if bp_match else ""

        # Evolved Persona
        ep_match = _re.search(r"\[EVOLVED PERSONA\].*?\n(.*?)(?=\n\[)", block, _re.DOTALL)
        rd["evolved_persona"] = ep_match.group(1).strip() if ep_match else rd["base_persona"]

        # Insights count
        ins_match = _re.search(r"\[EVOLVED PERSONA\]\s*\((\d+) insights?\)", block)
        rd["insights_count"] = int(ins_match.group(1)) if ins_match else 0

        # Extract reflection text (diff between evolved and base)
        refl_match = _re.search(r"Recent reflections: (.+?)$", rd["evolved_persona"], _re.MULTILINE | _re.DOTALL)
        rd["reflections"] = refl_match.group(1).strip() if refl_match else ""

        # Memory
        mem_match = _re.search(r"\[MEMORY\].*?\n(.*?)(?=\n\[)", block, _re.DOTALL)
        rd["memory"] = mem_match.group(1).strip() if mem_match else ""

        # Cognitive Traits
        ct_match = _re.search(r"\[COGNITIVE TRAITS\]\s*\n(.*?)(?=\n\[|\n─)", block, _re.DOTALL)
        rd["cognitive_traits"] = {}
        if ct_match:
            ct_text = ct_match.group(1).strip()
            for line in ct_text.split("\n"):
                line = line.strip()
                if ":" in line and "—" in line:
                    label_part, _, desc = line.partition("—")
                    label, _, val_str = label_part.partition(":")
                    label = label.strip()
                    try:
                        val = float(val_str.strip())
                    except ValueError:
                        val = 0.0
                    # Map Vietnamese labels to keys
                    key_map = {
                        "Độ bảo thủ": "conviction",
                        "Độ hay quên": "forgetfulness",
                        "Độ tò mò": "curiosity",
                        "Độ dễ bị ảnh hưởng": "impressionability",
                    }
                    key = key_map.get(label, label.lower().replace(" ", "_"))
                    rd["cognitive_traits"][key] = {
                        "value": val, "label": label, "description": desc.strip()
                    }

        # Interest Vector (weighted interests)
        iv_match = _re.search(r"\[INTEREST VECTOR\].*?\n(.*?)(?=\n\[|\n─)", block, _re.DOTALL)
        rd["interest_vector"] = []
        if iv_match:
            iv_text = iv_match.group(1).strip()
            for line in iv_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Parse: "📌 Music Cognition: 0.650 (profile, engaged 0x)"
                item_match = _re.match(
                    r"[📌🔄]\s*(.+?):\s*([\d.]+)\s*\((\w+),\s*engaged\s*(\d+)x\)(.*)",
                    line
                )
                if item_match:
                    kw = item_match.group(1).strip()
                    weight = float(item_match.group(2))
                    source = item_match.group(3)
                    eng_count = int(item_match.group(4))
                    flags = item_match.group(5).strip()
                    rd["interest_vector"].append({
                        "keyword": kw, "weight": weight, "source": source,
                        "engagement_count": eng_count,
                        "trending": "↑" in flags, "is_new": "NEW" in flags,
                    })

        # Search Queries (multi-query)
        sq_match = _re.search(r"\[SEARCH QUERIES\].*?\n(.*?)(?=\n\[|\n─)", block, _re.DOTALL)
        rd["search_queries"] = []
        if sq_match:
            sq_text = sq_match.group(1).strip()
            for line in sq_text.split("\n"):
                q_match = _re.match(r'q\d+\s*\(w=([\d.]+)\):\s*"(.+?)"', line.strip())
                if q_match:
                    rd["search_queries"].append({
                        "weight": float(q_match.group(1)),
                        "query": q_match.group(2),
                    })

        # Legacy: Drift Keywords (backward compat for old tracking files)
        drift_match = _re.search(r"\[DRIFT KEYWORDS\].*?\n(.*?)(?=\n\[)", block, _re.DOTALL)
        drift_text = drift_match.group(1).strip() if drift_match else ""
        if drift_text and drift_text != "(none)":
            rd["drift_keywords"] = [w.strip() for w in drift_text.split() if w.strip() and w != "(none)"]
        else:
            rd["drift_keywords"] = []

        # Legacy: Initial Interests (backward compat)
        ii_match = _re.search(r"\[INITIAL INTERESTS\].*?\n(.*?)(?=\n\[|\n─)", block, _re.DOTALL)
        ii_text = ii_match.group(1).strip() if ii_match else ""
        if ii_text and ii_text != "(none)":
            rd["initial_interests"] = [s.strip() for s in ii_text.split(",") if s.strip()]
        else:
            rd["initial_interests"] = []

        # Build display interests from vector or legacy
        if rd["interest_vector"]:
            rd["interest_query"] = ", ".join(
                f"{i['keyword']}({i['weight']:.2f})" for i in rd["interest_vector"][:5]
            )
        else:
            all_interests = rd["initial_interests"] + rd["drift_keywords"]
            rd["interest_query"] = ", ".join(all_interests) if all_interests else ""

        # Legacy: single search query
        old_sq = _re.search(r"\[SEARCH QUERY\]\s*\n(.*?)(?=\n\[|\n─)", block, _re.DOTALL)
        rd["search_query"] = old_sq.group(1).strip() if old_sq else ""

        # MBTI Modifiers
        mbti_match = _re.search(r"\[MBTI MODIFIERS\].*?\n\s*(.+?)(?=\n\[|\n─)", block, _re.DOTALL)
        rd["mbti_modifiers"] = mbti_match.group(1).strip() if mbti_match else ""

        # Graph Social Context
        graph_match = _re.search(r"\[GRAPH SOCIAL CONTEXT\]\s*\n(.*?)(?=\n\[|\n─)", block, _re.DOTALL)
        rd["graph_context"] = graph_match.group(1).strip() if graph_match else ""

        # Actions
        actions_match = _re.search(r"\[ACTIONS THIS ROUND\]\s*\n(.*?)(?=\n─|$)", block, _re.DOTALL)
        rd["actions"] = []
        if actions_match:
            for line in actions_match.group(1).strip().split("\n"):
                line = line.strip()
                if line and ":" in line:
                    atype, _, atext = line.partition(":")
                    rd["actions"].append({
                        "type": atype.strip(),
                        "text": atext.strip()
                    })

        rounds.append(rd)

    return {"agent": agent_info, "rounds": rounds, "total_rounds": len(rounds)}


@router.get("/{sim_id}/cognitive")
async def get_cognitive_tracking(sim_id: str):
    """Get parsed cognitive tracking data for the tracked agent(s).

    All paths come from meta.db via `_sim_paths(sim_id)`. Old code branched
    between in-memory state and resolver fallbacks; the helper hides both.
    """
    paths = _sim_paths(sim_id)
    jsonl_path = paths.get("tracking_path") or ""
    legacy_path = paths.get("tracking_legacy_path") or ""

    # Phase 5: touch last_accessed on cognitive query
    try:
        from ecosim_common.metadata_index import touch_sim_access
        touch_sim_access(sim_id)
    except Exception:
        pass

    if os.path.exists(jsonl_path) and os.path.getsize(jsonl_path) > 0:
        try:
            from agent_tracking_writer import parse_tracking_jsonl
            return parse_tracking_jsonl(jsonl_path)
        except Exception as e:
            logger.warning("JSONL parse fail, fallback to text: %s", e)

    if not os.path.exists(legacy_path):
        raise HTTPException(404, "Cognitive tracking file not found")

    try:
        return _parse_tracking_file(legacy_path)
    except Exception as e:
        raise HTTPException(500, f"Failed to parse tracking file: {e}")


# ══════════════════════════════════════════════════════════════════
# POST-SIMULATION: Enrich profiles with DB actions + KG summaries
# ══════════════════════════════════════════════════════════════════

FALKOR_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKOR_PORT = int(os.getenv("FALKORDB_PORT", "6379"))


def _extract_agent_actions_from_db(db_path: str, user_id: int) -> dict:
    """Extract all actions for one agent from the simulation DB."""
    result = {
        "posts": [], "comments": [], "likes_given": [],
        "received_comments": [], "shares_received": [],
        "trace_timeline": [], "stats": {}
    }
    if not os.path.exists(db_path):
        return result

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}

        # Posts by this agent
        if "post" in tables:
            cur.execute(
                "SELECT post_id, content, created_at, num_likes, num_dislikes, "
                "num_shares, original_post_id FROM post WHERE user_id=? ORDER BY created_at",
                (user_id,))
            result["posts"] = [dict(r) for r in cur.fetchall()]

        # Comments by this agent
        if "comment" in tables:
            cur.execute(
                "SELECT c.content, c.created_at, c.num_likes, c.post_id, "
                "p.content as on_post, u.name as post_author "
                "FROM comment c LEFT JOIN post p ON c.post_id=p.post_id "
                "LEFT JOIN user u ON p.user_id=u.user_id "
                "WHERE c.user_id=? ORDER BY c.created_at", (user_id,))
            result["comments"] = [dict(r) for r in cur.fetchall()]

        # Posts this agent liked
        if "like" in tables and "post" in tables:
            cur.execute(
                "SELECT p.content, u.name as author FROM [like] l "
                "JOIN post p ON l.post_id=p.post_id "
                "LEFT JOIN user u ON p.user_id=u.user_id "
                "WHERE l.user_id=?", (user_id,))
            result["likes_given"] = [dict(r) for r in cur.fetchall()]

        # Comments others left on this agent's posts
        if "comment" in tables and "post" in tables:
            cur.execute(
                "SELECT c.content, u.name as commenter "
                "FROM comment c JOIN post p ON c.post_id=p.post_id "
                "LEFT JOIN user u ON c.user_id=u.user_id "
                "WHERE p.user_id=? AND c.user_id!=?", (user_id, user_id))
            result["received_comments"] = [dict(r) for r in cur.fetchall()]

        # Shares of this agent's posts
        if "post" in tables:
            cur.execute(
                "SELECT rp.content, u.name as sharer "
                "FROM post rp LEFT JOIN user u ON rp.user_id=u.user_id "
                "WHERE rp.original_post_id IN (SELECT post_id FROM post WHERE user_id=?) "
                "AND rp.user_id!=?", (user_id, user_id))
            result["shares_received"] = [dict(r) for r in cur.fetchall()]

        # Trace timeline (skip sign_up)
        if "trace" in tables:
            cur.execute(
                "SELECT action, info, created_at FROM trace "
                "WHERE user_id=? AND action!='sign_up' ORDER BY created_at", (user_id,))
            raw_traces = [dict(r) for r in cur.fetchall()]
            for t in raw_traces:
                entry = {"action": t["action"], "round": t.get("created_at", "")}
                if t.get("info"):
                    try:
                        info = json.loads(t["info"]) if isinstance(t["info"], str) else t["info"]
                        if isinstance(info, dict) and "content" in info:
                            entry["detail"] = str(info["content"])[:150]
                    except (json.JSONDecodeError, TypeError):
                        pass
                result["trace_timeline"].append(entry)

        # Summary stats
        total_engagement = sum(
            (p.get("num_likes", 0) or 0) + (p.get("num_shares", 0) or 0)
            for p in result["posts"]
        )
        result["stats"] = {
            "total_posts": len(result["posts"]),
            "total_comments": len(result["comments"]),
            "total_likes_given": len(result["likes_given"]),
            "total_received_comments": len(result["received_comments"]),
            "total_shares_received": len(result["shares_received"]),
            "total_engagement_received": total_engagement,
            "total_trace_actions": len(result["trace_timeline"]),
        }
    finally:
        conn.close()

    return result


async def _query_kg_for_agent(group_id: str, agent_name: str) -> list:
    """Query KG using Graphiti hybrid_search_rrf by agent name.
    
    Searches for the agent's name, retrieves top 15 nodes (entities)
    containing their simulation actions and campaign context.
    Also retrieves related edges (facts) as supplementary data.
    """
    results = []
    graphiti_instance = None
    try:
        from ecosim_common.graphiti_factory import make_graphiti, make_falkor_driver
        from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF

        # Verify graph exists — fail loud thay vì fallback sang graph khác.
        # Sau khi master+fork architecture, graph name = sim_<sim_id> phải tồn
        # tại do được fork lúc prepare. Nếu thiếu → bug đáng warn.
        from falkordb import FalkorDB
        fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
        available = fdb.list_graphs()

        if group_id not in available:
            logger.warning(
                "KG query: graph '%s' not in FalkorDB (available=%s). "
                "Sim đã được prepare đúng cách chưa? Trả empty.",
                group_id, available,
            )
            return []
        db_name = group_id

        # Connect Graphiti to the specific graph database
        driver = make_falkor_driver(host=FALKOR_HOST, port=FALKOR_PORT, database=db_name)
        graphiti_instance = make_graphiti(driver)

        # Hybrid search with RRF: query by agent name, get 15 results
        search_config = COMBINED_HYBRID_SEARCH_RRF
        search_config.limit = 15

        search_results = await graphiti_instance.search_(
            query=agent_name,
            config=search_config,
            group_ids=[db_name],
        )

        # PRIMARY: Extract nodes (entities) — these contain agent actions + campaign entities
        for node in (search_results.nodes or []):
            name = getattr(node, 'name', '') or ''
            summary = getattr(node, 'summary', '') or ''
            if name or summary:
                results.append({
                    "name": name,
                    "summary": summary[:500],
                    "type": "node",
                })

        # SUPPLEMENTARY: Extract edges (facts/relationships)
        for edge in (search_results.edges or []):
            fact = getattr(edge, 'fact', '') or ''
            edge_name = getattr(edge, 'name', '') or ''
            if fact:
                results.append({
                    "name": edge_name,
                    "fact": fact[:400],
                    "type": "edge",
                })

        logger.info(
            f"Graphiti hybrid_search_rrf for '{agent_name}' on graph '{db_name}': "
            f"{len(search_results.nodes or [])} nodes, "
            f"{len(search_results.edges or [])} edges"
        )

    except Exception as e:
        logger.warning(f"KG hybrid search failed for '{agent_name}' on '{group_id}': {e}")
    finally:
        if graphiti_instance:
            try:
                await graphiti_instance.close()
            except Exception:
                pass

    return results


async def _llm_summarize_kg(agent_name: str, raw_entities: list) -> str:
    """Summarize KG search results into agent simulation context.
    
    The KG contains agent-specific facts extracted from posts/comments via
    Phase 15 Zep section dispatch (sim_zep_section_writer), plus campaign entities.
    LLM builds a narrative about what this specific agent did.
    """
    if not raw_entities:
        return ""

    # Build structured data from nodes (primary) and edges (supplementary)
    node_lines = []
    edge_lines = []
    for e in raw_entities:
        if e.get("type") == "node":
            name = e.get('name', '')
            summary = e.get('summary', '')
            if name or summary:
                node_lines.append(f"- {name}: {summary[:400]}")
        elif e.get("type") == "edge":
            fact = e.get('fact', '')
            if fact:
                edge_lines.append(f"- {fact[:300]}")

    if not node_lines and not edge_lines:
        return ""

    raw_text = ""
    if node_lines:
        raw_text += "ENTITIES (nodes):\n" + "\n".join(node_lines) + "\n\n"
    if edge_lines:
        raw_text += "FACTS (edges):\n" + "\n".join(edge_lines)

    import httpx
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")

    prompt = (
        f'Du lieu duoi day la ket qua tim kiem tren Knowledge Graph khi tra ten "{agent_name}".\n'
        f'Hay tom tat thanh DANH SACH GAU DAU tieng Viet, toi da 8 muc, moi muc 1 dong ngan gon.\n'
        f'Tap trung vao:\n'
        f'1. Nhung gi "{agent_name}" DA LAM: dang bai gi, binh luan gi, thich bai cua ai.\n'
        f'2. Ai da tuong tac voi "{agent_name}": ai thich bai, ai binh luan.\n'
        f'3. Boi canh chien dich (ten, thoi gian) - chi 1 dong.\n\n'
        f'QUY TAC:\n'
        f'- Moi muc bat dau bang dau "-", toi da 1 dong.\n'
        f'- KHONG viet van xuoi, KHONG giai thich dai dong.\n'
        f'- KHONG dung markdown (**, ##), KHONG dung emoji.\n'
        f'- CHI su dung thong tin CO TRONG du lieu.\n\n'
        f'DU LIEU:\n{raw_text}'
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Ban la tro ly tom tat du lieu mo phong. Tra loi tieng Viet, dang danh sach gau dau ngan gon, khong markdown, khong emoji. Chi dung thong tin co san."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 250,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            result = resp.json()["choices"][0]["message"]["content"].strip()
            # Strip any remaining markdown formatting
            import re
            result = re.sub(r'\*\*([^*]+)\*\*', r'\1', result)
            result = re.sub(r'^\s*#+\s*', '', result, flags=re.MULTILINE)
            result = re.sub(r'^\s*\*\s+', '- ', result, flags=re.MULTILINE)
            return result
    except Exception as e:
        logger.warning(f"LLM summarize failed for {agent_name}: {e}")
        # Fallback: deduplicated node names + edge facts
        seen = set()
        names = []
        facts = []
        for x in raw_entities:
            n = x.get("name", "")
            if n and n not in seen:
                seen.add(n)
                names.append(n)
            f = x.get("fact", "")
            if f and f not in seen:
                seen.add(f)
                facts.append(f[:200])
        parts = []
        if names:
            parts.append("Cac thuc the lien quan: " + ", ".join(names[:10]))
        if facts:
            parts.append("Su kien: " + "; ".join(facts[:5]))
        return ". ".join(parts) if parts else ""


async def _enrich_profiles_after_sim(sim_id: str, sim_dir: str, group_id: str):
    """Post-simulation: enrich each agent profile with DB actions + KG summary.

    Reads profiles.json, enriches each profile, writes back. Paths come
    from meta.db (sim_dir kept for backward-compat with legacy callers).
    """
    paths = _sim_paths(sim_id)
    profiles_path = paths.get("profiles_path") or os.path.join(sim_dir, "profiles.json")
    db_path = paths.get("oasis_db_path") or os.path.join(sim_dir, "oasis_simulation.db")

    if not os.path.exists(profiles_path):
        logger.warning(f"No profiles.json at {profiles_path}")
        return

    with open(profiles_path, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    logger.info(f"[{sim_id}] Enriching {len(profiles)} agent profiles...")

    for i, profile in enumerate(profiles):
        user_id = profile.get("agent_id", i) + 1
        agent_name = profile.get("realname", profile.get("name", f"Agent_{i}"))

        # 1. Extract actions from simulation DB (may not exist if sim hasn't run)
        if os.path.exists(db_path):
            try:
                actions = _extract_agent_actions_from_db(db_path, user_id)
            except Exception as e:
                logger.warning(f"DB extraction failed for agent {agent_name}: {e}")
                actions = {"stats": {}, "posts": [], "comments": [], "likes_given": [], "received_comments": [], "shares_received": [], "trace_timeline": []}
        else:
            actions = {"stats": {}, "posts": [], "comments": [], "likes_given": [], "received_comments": [], "shares_received": [], "trace_timeline": []}

        # 2. Query KG using Graphiti hybrid_search_rrf
        raw_kg = await _query_kg_for_agent(group_id, agent_name)

        # 3. LLM summarize KG data
        kg_summary = await _llm_summarize_kg(agent_name, raw_kg)

        # 4. Write enriched data into the profile
        profile["sim_actions"] = {
            "stats": actions["stats"],
            "posts": [
                {"content": p.get("content", ""), "likes": p.get("num_likes", 0),
                 "dislikes": p.get("num_dislikes", 0), "shares": p.get("num_shares", 0),
                 "is_repost": p.get("original_post_id") is not None}
                for p in actions["posts"]
            ],
            "comments": [
                {"content": c.get("content", ""), "on_post": str(c.get("on_post", ""))[:200],
                 "post_author": c.get("post_author", "?")}
                for c in actions["comments"]
            ],
            "likes_given": [
                {"content": str(l.get("content", ""))[:200], "author": l.get("author", "?")}
                for l in actions["likes_given"]
            ],
            "received_comments": [
                {"content": rc.get("content", ""), "commenter": rc.get("commenter", "?")}
                for rc in actions["received_comments"]
            ],
            "shares_received": [
                {"content": str(s.get("content", ""))[:200], "sharer": s.get("sharer", "?")}
                for s in actions["shares_received"]
            ],
            "trace_timeline": actions["trace_timeline"][:50],  # cap at 50
        }
        profile["graph_context"] = kg_summary
        profile["enriched_at"] = datetime.utcnow().isoformat()

        stats = actions.get("stats", {})
        logger.info(f"  Agent {i} ({agent_name}): {stats.get('total_posts', 0)} posts, "
                     f"{stats.get('total_comments', 0)} comments, "
                     f"{len(raw_kg)} KG entities")

    # Write enriched profiles back
    with open(profiles_path, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)

    logger.info(f"[{sim_id}] Enriched profiles saved to {profiles_path}")


@router.post("/{sim_id}/enrich-profiles")
async def enrich_profiles(sim_id: str):
    """Manually trigger profile enrichment with simulation data + KG context."""
    paths = _sim_paths(sim_id)
    sim_dir = paths.get("sim_dir") or os.path.join(SIM_DIR, sim_id)
    profiles_path = paths.get("profiles_path") or ""
    config_path = paths.get("config_path") or ""

    if not os.path.isdir(sim_dir):
        raise HTTPException(404, f"Simulation {sim_id} not found")
    if not profiles_path or not os.path.exists(profiles_path):
        raise HTTPException(404, "No profiles.json found")

    # Determine group_id — prefer in-memory state, else read from config.json
    state = _simulations.get(sim_id)
    if state:
        group_id = state.group_id or sim_id
    elif config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        group_id = cfg.get("group_id", sim_id)
    else:
        group_id = sim_id

    try:
        await _enrich_profiles_after_sim(sim_id, sim_dir, group_id)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Enrichment failed for {sim_id}: {e}\n{tb}")
        raise HTTPException(500, f"Enrichment failed: {str(e)}")

    # Read back to return stats
    with open(profiles_path, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    enriched_count = sum(1 for p in profiles if p.get("enriched_at"))
    return {
        "sim_id": sim_id,
        "enriched": enriched_count,
        "total": len(profiles),
        "status": "done",
    }


# ── Lazy per-agent enrichment ──

async def _enrich_single_agent(sim_id: str, agent_id: int) -> dict:
    """Enrich a SINGLE agent on demand (lazy enrichment).

    Returns the enriched profile dict. Skips if already enriched.
    Used by interview/analysis to avoid enriching all 1000 agents.
    """
    state = _simulations.get(sim_id)
    sim_dir = state.output_dir if state else os.path.join(SIM_DIR, sim_id)
    profiles_path = os.path.join(sim_dir, "profiles.json")
    db_path = os.path.join(sim_dir, "oasis_simulation.db")

    if not os.path.exists(profiles_path):
        raise HTTPException(404, "No profiles.json found")

    with open(profiles_path, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    if agent_id < 0 or agent_id >= len(profiles):
        raise HTTPException(404, f"Agent {agent_id} not found")

    profile = profiles[agent_id]

    # Skip if already enriched
    if profile.get("enriched_at"):
        return profile

    # Determine group_id
    group_id = ""
    if state:
        group_id = state.group_id or sim_id
    else:
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as cf:
                cfg = json.load(cf)
            group_id = cfg.get("group_id", sim_id)
        else:
            group_id = sim_id

    user_id = profile.get("agent_id", agent_id) + 1
    agent_name = profile.get("realname", profile.get("name", f"Agent_{agent_id}"))

    logger.info(f"[{sim_id}] Lazy-enriching agent {agent_id} ({agent_name})...")

    # 1. Extract actions from simulation DB
    if os.path.exists(db_path):
        try:
            actions = _extract_agent_actions_from_db(db_path, user_id)
        except Exception as e:
            logger.warning(f"DB extraction failed for agent {agent_name}: {e}")
            actions = {"stats": {}, "posts": [], "comments": [], "likes_given": [],
                       "received_comments": [], "shares_received": [], "trace_timeline": []}
    else:
        actions = {"stats": {}, "posts": [], "comments": [], "likes_given": [],
                   "received_comments": [], "shares_received": [], "trace_timeline": []}

    # 2. Query KG
    raw_kg = await _query_kg_for_agent(group_id, agent_name)

    # 3. LLM summarize KG data (compressed bullet points)
    kg_summary = await _llm_summarize_kg(agent_name, raw_kg)

    # 4. Write enriched data into the profile
    profile["sim_actions"] = {
        "stats": actions["stats"],
        "posts": [
            {"content": p.get("content", ""), "likes": p.get("num_likes", 0),
             "dislikes": p.get("num_dislikes", 0), "shares": p.get("num_shares", 0),
             "is_repost": p.get("original_post_id") is not None}
            for p in actions["posts"]
        ],
        "comments": [
            {"content": c.get("content", ""), "on_post": str(c.get("on_post", ""))[:200],
             "post_author": c.get("post_author", "?")}
            for c in actions["comments"]
        ],
        "likes_given": [
            {"content": str(l.get("content", ""))[:200], "author": l.get("author", "?")}
            for l in actions["likes_given"]
        ],
        "received_comments": [
            {"content": rc.get("content", ""), "commenter": rc.get("commenter", "?")}
            for rc in actions["received_comments"]
        ],
        "shares_received": [
            {"content": str(s.get("content", ""))[:200], "sharer": s.get("sharer", "?")}
            for s in actions["shares_received"]
        ],
        "trace_timeline": actions["trace_timeline"][:50],
    }
    profile["graph_context"] = kg_summary
    profile["enriched_at"] = datetime.utcnow().isoformat()

    # Persist back to profiles.json (only this agent changed)
    profiles[agent_id] = profile
    with open(profiles_path, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)

    stats = actions.get("stats", {})
    logger.info(f"  Agent {agent_id} ({agent_name}): {stats.get('total_posts', 0)} posts, "
                f"{stats.get('total_comments', 0)} comments, {len(raw_kg)} KG entities — DONE")

    return profile


@router.post("/{sim_id}/enrich-agent/{agent_id}")
async def enrich_single_agent_endpoint(sim_id: str, agent_id: int):
    """Lazy enrich a single agent on demand."""
    try:
        profile = await _enrich_single_agent(sim_id, agent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lazy enrichment failed for {sim_id}/agent {agent_id}: {e}")
        raise HTTPException(500, f"Enrichment failed: {str(e)}")

    return {
        "sim_id": sim_id,
        "agent_id": agent_id,
        "agent_name": profile.get("realname", ""),
        "enriched_at": profile.get("enriched_at", ""),
        "graph_context_len": len(profile.get("graph_context", "")),
        "status": "done",
    }

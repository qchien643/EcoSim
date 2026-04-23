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
from typing import Dict, List, Optional

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


# ── Request Models ──
class CrisisEventDef(BaseModel):
    """Crisis event definition for scheduled or real-time injection."""
    trigger_round: int = 1
    crisis_type: str = "custom"  # price_change|scandal|news|competitor|regulation|positive_event|custom
    title: str = "Crisis Event"
    description: str = ""
    severity: float = 0.5        # 0.0 (mild) → 1.0 (catastrophic)
    affected_domains: List[str] = []
    sentiment_shift: str = "negative"  # negative|positive|mixed
    interest_keywords: List[str] = []


class PrepareRequest(BaseModel):
    campaign_id: str
    num_agents: int = 10
    num_rounds: int = 3
    group_id: str = ""
    cognitive_toggles: Dict[str, bool] = {}
    tracked_agent_id: int = 0
    crisis_events: List[CrisisEventDef] = []  # Scheduled crisis events

class StartRequest(BaseModel):
    sim_id: str
    group_id: str = ""


# ── Profile Generator ──
import hashlib
import random as _random

_VN_FIRST_M = ["Minh", "Hoang", "Duc", "Tuan", "Hieu", "Long", "Thanh", "Khanh", "Phuc", "Duy",
               "Bao", "Quang", "Trung", "Khoi", "Dat", "Cuong", "Hung", "Tai", "Vinh", "Tien"]
_VN_FIRST_F = ["Linh", "Trang", "Mai", "Ngoc", "Huong", "Thao", "Lan", "Phuong", "Ha", "Nhu",
               "Yen", "Chi", "Quynh", "Hanh", "Diem", "Thu", "My", "Anh", "Van", "Hoa"]
_VN_LAST = ["Nguyen", "Tran", "Le", "Pham", "Hoang", "Vu", "Vo", "Dang", "Bui", "Do",
            "Ngo", "Duong", "Ly", "Trinh", "Luu", "Phan", "Dinh", "Truong", "Huynh", "Lam"]
_VN_MIDDLE = ["Van", "Thi", "Xuan", "Minh", "Quoc", "Dinh", "Ngoc", "Thanh", "Duc", "Huu"]
_MBTI = ["INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
         "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP"]

# Parquet source for rich persona data (resolve relative to ECOSIM_ROOT)
_PARQUET_PATH = os.path.join(ECOSIM_ROOT, "data", "dataGenerator", "profile.parquet")


def _sample_parquet_personas(n: int) -> list[dict]:
    """Sample N random persona records from profile.parquet using duckdb."""
    import duckdb
    con = duckdb.connect()
    rows = con.sql(f"""
        SELECT
            json->>'persona'                          AS persona,
            json->>'general domain (top 1 percent)'   AS general_domain,
            json->>'specific domain (top 1 percent)'  AS specific_domain,
            json->>'general domain (top 0.1 percent)' AS general_domain_rare,
            json->>'specific domain (top 0.1 percent)' AS specific_domain_rare
        FROM '{_PARQUET_PATH}'
        USING SAMPLE {n}
    """).fetchall()
    con.close()

    results = []
    for persona, gd, sd, gdr, sdr in rows:
        # Strip surrounding quotes if present
        persona = (persona or "").strip().strip('"')
        gd = (gd or "").strip().strip('"')
        sd = (sd or "").strip().strip('"')
        gdr = (gdr or "").strip().strip('"')
        sdr = (sdr or "").strip().strip('"')

        # Pick best available domain (prefer top 0.1%, fallback to top 1%)
        gen_domain = gdr if gdr and gdr != "None" else (gd if gd and gd != "None" else "")
        spec_domain = sdr if sdr and sdr != "None" else (sd if sd and sd != "None" else "")

        results.append({
            "persona": persona,
            "general_domain": gen_domain,
            "specific_domain": spec_domain,
        })
    return results


async def _get_consumer_campaign_context(campaign_spec: dict) -> str:
    """Query Graphiti for campaign knowledge and use LLM to rewrite
    into a consumer-friendly summary (discarding KPIs, risks, etc.)."""
    campaign_name = campaign_spec.get("name", "")
    campaign_summary = campaign_spec.get("summary", "")
    timeline = campaign_spec.get("timeline", "")
    market = campaign_spec.get("market", "")

    # Try Graphiti for richer context
    graphiti_facts = ""
    try:
        from graphiti_core import Graphiti
        from graphiti_core.driver.falkordb_driver import FalkorDriver
        from graphiti_core.search.search_config_recipes import SearchMethod

        driver = FalkorDriver(host="localhost", port=6379, database="default_db")
        graphiti = Graphiti(graph_driver=driver)
        results = await graphiti.search(
            query=f"{campaign_name} promotions deals products discounts",
            num_results=10,
            search_method=SearchMethod.COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
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


async def _generate_profiles(num_agents: int, campaign_spec: dict) -> list:
    """Generate N agent profiles from parquet personas + Graphiti campaign context.

    Approach:
    1. Sample N rich persona records from profile.parquet (avg ~585 chars each)
    2. Keep original persona text + domain fields intact
    3. Assign Vietnamese name, age, gender, MBTI
    4. Describe social media activity in natural language
    5. Inject consumer-focused campaign context (Graphiti + LLM rewrite)
    """
    rng = _random.Random()  # time-based seed

    # Step 1: Get consumer-friendly campaign context
    consumer_context = await _get_consumer_campaign_context(campaign_spec)
    logger.info("Consumer campaign context (%d chars): %s", len(consumer_context), consumer_context[:200])

    # Step 2: Sample personas from parquet
    try:
        parquet_rows = _sample_parquet_personas(num_agents)
        logger.info("Sampled %d personas from parquet", len(parquet_rows))
    except Exception as e:
        logger.error("Failed to read parquet: %s — generating fallback personas", e)
        parquet_rows = [{"persona": "A regular social media user.", "general_domain": "", "specific_domain": ""}] * num_agents

    profiles = []
    used_names = set()

    for i in range(num_agents):
        pq = parquet_rows[i] if i < len(parquet_rows) else parquet_rows[-1]

        # Vietnamese identity
        gender = rng.choice(["female", "male"])
        first_pool = _VN_FIRST_F if gender == "female" else _VN_FIRST_M
        for _ in range(50):
            first = rng.choice(first_pool)
            last = rng.choice(_VN_LAST)
            middle = rng.choice(_VN_MIDDLE)
            realname = f"{last} {middle} {first}"
            if realname not in used_names:
                used_names.add(realname)
                break

        age = rng.randint(18, 55)
        mbti = rng.choice(_MBTI)
        username = f"{first.lower()}_{last.lower()}_{rng.randint(100, 999)}"

        # Social media metrics (random but realistic)
        follower_count = rng.choice([
            rng.randint(50, 300), rng.randint(300, 1500),
            rng.randint(1500, 5000), rng.randint(5000, 20000),
        ])
        account_age_years = rng.randint(1, 8)
        posts_per_week = rng.choice([1, 2, 3, 5, 7, 10, 15])
        daily_hours = rng.choice([0.5, 1, 1.5, 2, 3, 4])

        # Describe social media activity in natural language
        if posts_per_week <= 2:
            activity_desc = "a casual social media user who occasionally browses and posts"
        elif posts_per_week <= 5:
            activity_desc = "a regular social media user who checks the platform daily and posts a few times a week"
        elif posts_per_week <= 10:
            activity_desc = "an active social media user who posts almost every day and follows trends closely"
        else:
            activity_desc = "a highly active social media user who posts multiple times daily and is always up to date"

        if follower_count < 300:
            reach_desc = f"a small personal network of about {follower_count} followers"
        elif follower_count < 2000:
            reach_desc = f"a moderate following of around {follower_count} people"
        elif follower_count < 8000:
            reach_desc = f"a substantial audience of about {follower_count} followers"
        else:
            reach_desc = f"a large following of {follower_count} followers, making them a micro-influencer"

        # Domain line
        domain_line = ""
        if pq["general_domain"] and pq["specific_domain"]:
            domain_line = f"Domain expertise: {pq['general_domain']}, specifically {pq['specific_domain']}."
        elif pq["general_domain"]:
            domain_line = f"Domain expertise: {pq['general_domain']}."
        elif pq["specific_domain"]:
            domain_line = f"Domain expertise: {pq['specific_domain']}."

        # === Build final persona ===
        persona_parts = [
            f"{realname} is a {age}-year-old {'female' if gender == 'female' else 'male'} from Vietnam.",
            "",
            pq["persona"],  # FULL original parquet persona — no truncation
        ]
        if domain_line:
            persona_parts.append(domain_line)
        persona_parts.extend([
            "",
            f"On social media, {realname} is {activity_desc}. "
            f"They have {reach_desc} and have been active for {account_age_years} years, "
            f"spending roughly {daily_hours} hours a day on the platform.",
            "",
            f"Campaign awareness: {consumer_context}",
        ])
        persona = "\n".join(persona_parts)

        # Bio for recommendation system (shorter, for recsys similarity)
        bio = (
            f"{realname}, {age}y, {'F' if gender == 'female' else 'M'}. "
            f"{pq['persona'][:200]} "
            f"{domain_line} "
            f"{consumer_context[:150]}"
        )

        profiles.append({
            "realname": realname,
            "username": username,
            "bio": bio,
            "persona": persona,
            "age": age,
            "gender": gender,
            "mbti": mbti,
            "country": "Vietnam",
            # Original parquet data (preserved for analysis)
            "original_persona": pq["persona"],
            "general_domain": pq["general_domain"],
            "specific_domain": pq["specific_domain"],
            # Social media stats (for frontend)
            "follower_count": follower_count,
            "account_age_years": account_age_years,
            "posts_per_week": posts_per_week,
            "daily_hours": daily_hours,
        })

    return profiles


# ── POST /api/sim/prepare ──
@router.post("/prepare")
async def prepare_simulation(req: PrepareRequest):
    """Prepare simulation: generate profiles + config.
    
    This uses the Core Service's campaign data (via shared uploads dir)
    and generates OASIS-compatible agent profiles.
    """
    # Verify campaign exists
    spec_path = os.path.join(UPLOAD_DIR, f"{req.campaign_id}_spec.json")
    if not os.path.exists(spec_path):
        raise HTTPException(404, f"Campaign {req.campaign_id} not found at {spec_path}")
    
    # Create simulation state
    sim_id = f"sim_{uuid.uuid4().hex[:8]}"
    sim_dir = os.path.join(SIM_DIR, sim_id)
    os.makedirs(sim_dir, exist_ok=True)
    
    state = SimState(
        sim_id=sim_id,
        status=SimStatus.PREPARING,
        campaign_id=req.campaign_id,
        num_agents=req.num_agents,
        total_rounds=req.num_rounds,
        output_dir=sim_dir,
        created_at=datetime.now().isoformat(),
        group_id=req.group_id or sim_id,
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
        
        # Save config with full campaign data
        config = {
            "sim_id": sim_id,
            "campaign_id": req.campaign_id,
            "num_agents": req.num_agents,
            "num_rounds": req.num_rounds,
            "group_id": state.group_id,
            "campaign_context": campaign_context,
            "campaign_name": spec.get("name", ""),
            "campaign_market": spec.get("market", ""),
            "campaign_summary": spec.get("summary", ""),
            "stakeholders": spec.get("stakeholders", []),
            "kpis": spec.get("kpis", []),
            "created_at": state.created_at,
            # Cognitive pipeline settings
            "enable_agent_memory": req.cognitive_toggles.get("enable_agent_memory", True),
            "enable_mbti_modifiers": req.cognitive_toggles.get("enable_mbti_modifiers", True),
            "enable_interest_drift": req.cognitive_toggles.get("enable_interest_drift", True),
            "enable_reflection": req.cognitive_toggles.get("enable_reflection", True),
            "enable_graph_cognition": req.cognitive_toggles.get("enable_graph_cognition", False),
            "tracked_agent_id": req.tracked_agent_id,
            # Crisis injection events (scheduled)
            "crisis_events": [e.model_dump() for e in req.crisis_events] if req.crisis_events else [],
        }
        config_path = os.path.join(sim_dir, "simulation_config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        # Generate N agent profiles (async: parquet + Graphiti + LLM)
        profiles_path = os.path.join(sim_dir, "profiles.json")
        profiles = await _generate_profiles(req.num_agents, spec)
        with open(profiles_path, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
        logger.info(f"Generated {len(profiles)} agent profiles to {profiles_path}")
        
        state.status = SimStatus.READY
        
        return {
            "sim_id": sim_id,
            "status": "ready",
            "group_id": state.group_id,
            "output_dir": sim_dir,
            "config_path": config_path,
            "num_agents": req.num_agents,
            "num_rounds": req.num_rounds,
        }
        
    except Exception as e:
        state.status = SimStatus.FAILED
        state.error = str(e)
        raise HTTPException(500, str(e))


# ── POST /api/sim/start ──
@router.post("/start")
async def start_simulation(req: StartRequest):
    """Start OASIS simulation as subprocess."""
    state = _simulations.get(req.sim_id)
    if not state:
        raise HTTPException(404, f"Simulation {req.sim_id} not found")
    
    if state.status not in (SimStatus.READY, SimStatus.COMPLETED, SimStatus.FAILED, SimStatus.RUNNING):
        raise HTTPException(400, f"Simulation must be READY, current: {state.status}")
    
    group_id = req.group_id or state.group_id or req.sim_id
    
    # Kill any previous process for this sim (re-run scenario)
    old_proc = _processes.get(req.sim_id)
    if old_proc and old_proc.poll() is None:
        logger.info(f"Killing previous simulation process {old_proc.pid}")
        old_proc.kill()
        old_proc.wait()
    _processes.pop(req.sim_id, None)
    
    # Build subprocess command
    run_script = os.path.join(SCRIPT_DIR, "run_simulation.py")
    cmd = [OASIS_VENV_PYTHON, run_script, "--group-id", group_id, "--sim-dir", state.output_dir]
    
    logger.info(f"Starting simulation: {cmd}")
    
    # Set PYTHONIOENCODING to avoid cp1252 errors on Windows
    sub_env = os.environ.copy()
    sub_env["PYTHONIOENCODING"] = "utf-8"
    
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
        _processes[req.sim_id] = proc
        state.status = SimStatus.RUNNING
        state.group_id = group_id
        
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
    """Get simulation status."""
    state = _simulations.get(sim_id)
    if not state:
        raise HTTPException(404, f"Simulation {sim_id} not found")
    
    return state.model_dump()


# ── GET /api/sim/list ──
@router.get("/list")
async def list_simulations():
    """List all simulations."""
    # Scan disk for existing simulations
    _scan_disk()
    sims = [s.model_dump() for s in _simulations.values()]
    return {"simulations": sims, "count": len(sims)}


# ── GET /api/sim/{sim_id}/profiles ──
@router.get("/{sim_id}/profiles")
async def get_profiles(sim_id: str):
    """Get agent profiles for a simulation."""
    state = _simulations.get(sim_id)
    sim_dir = state.output_dir if state else os.path.join(SIM_DIR, sim_id)
    
    json_path = os.path.join(sim_dir, "profiles.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            profiles = json.load(f)
        return {"profiles": profiles, "count": len(profiles)}
    
    raise HTTPException(404, "Profiles not found")


# ── GET /api/sim/{sim_id}/config ──
@router.get("/{sim_id}/config")
async def get_config(sim_id: str):
    """Get simulation config."""
    state = _simulations.get(sim_id)
    sim_dir = state.output_dir if state else os.path.join(SIM_DIR, sim_id)
    
    config_path = os.path.join(sim_dir, "simulation_config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    raise HTTPException(404, "Config not found")


# ── GET /api/sim/{sim_id}/actions ──
@router.get("/{sim_id}/actions")
async def get_actions(sim_id: str):
    """Get simulation actions from actions.jsonl."""
    state = _simulations.get(sim_id)
    sim_dir = state.output_dir if state else os.path.join(SIM_DIR, sim_id)
    
    actions_path = os.path.join(sim_dir, "actions.jsonl")
    if not os.path.exists(actions_path):
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
    
    progress_path = os.path.join(state.output_dir, "progress.json")
    if os.path.exists(progress_path):
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
    
    async def event_generator():
        last_round = -1
        last_action_count = 0
        
        while True:
            # Read progress from file
            progress_path = os.path.join(state.output_dir, "progress.json")
            current_round = 0
            total_rounds = state.total_rounds
            file_status = "waiting"
            
            if os.path.exists(progress_path):
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
                actions_path = os.path.join(state.output_dir, "actions.jsonl")
                if os.path.exists(actions_path):
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
            log_path = os.path.join(state.output_dir, "simulation.log")
            if os.path.exists(log_path):
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
    """Scan disk for existing simulation directories + progress files."""
    if not os.path.isdir(SIM_DIR):
        return
    for entry in os.listdir(SIM_DIR):
        if entry.startswith("sim_") and entry not in _simulations:
            sim_dir = os.path.join(SIM_DIR, entry)
            config_path = os.path.join(sim_dir, "simulation_config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    
                    # Determine status from progress.json if available
                    status = SimStatus.READY
                    current_round = 0
                    total_rounds = cfg.get("num_rounds", 3)
                    
                    progress_path = os.path.join(sim_dir, "progress.json")
                    if os.path.exists(progress_path):
                        try:
                            with open(progress_path, "r") as pf:
                                prog = json.load(pf)
                            current_round = prog.get("current_round", 0)
                            total_rounds = prog.get("total_rounds", total_rounds)
                            pstatus = prog.get("status", "")
                            if pstatus == "completed":
                                status = SimStatus.COMPLETED
                            elif pstatus == "running":
                                status = SimStatus.COMPLETED  # process died but had progress
                        except Exception:
                            pass
                    elif os.path.exists(os.path.join(sim_dir, "actions.jsonl")):
                        status = SimStatus.COMPLETED
                    
                    _simulations[entry] = SimState(
                        sim_id=entry,
                        status=status,
                        campaign_id=cfg.get("campaign_id", ""),
                        num_agents=cfg.get("num_agents", 0),
                        total_rounds=total_rounds,
                        current_round=current_round,
                        output_dir=sim_dir,
                        created_at=cfg.get("created_at", ""),
                        group_id=cfg.get("group_id", entry),
                    )
                except Exception:
                    pass


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
    
    # Write pending crisis file for subprocess to pick up
    pending_path = os.path.join(state.output_dir, "pending_crisis.json")
    
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


# ── GET /api/sim/{sim_id}/crisis-log ──
@router.get("/{sim_id}/crisis-log")
async def get_crisis_log(sim_id: str):
    """Get the log of all crisis events that have been triggered in a simulation."""
    state = _simulations.get(sim_id)
    sim_dir = state.output_dir if state else os.path.join(SIM_DIR, sim_id)
    
    log_path = os.path.join(sim_dir, "crisis_log.json")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                return {"crisis_log": json.load(f)}
        except Exception:
            pass
    
    return {"crisis_log": []}


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
    """Get parsed cognitive tracking data for the tracked agent."""
    state = _simulations.get(sim_id)
    sim_dir = state.output_dir if state else os.path.join(SIM_DIR, sim_id)

    tracking_path = os.path.join(sim_dir, "agent_tracking.txt")
    if not os.path.exists(tracking_path):
        raise HTTPException(404, "Cognitive tracking file not found")

    try:
        data = _parse_tracking_file(tracking_path)
        return data
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
        from graphiti_core import Graphiti
        from graphiti_core.driver.falkordb_driver import FalkorDriver
        from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF

        # Determine which graph database to connect to
        from falkordb import FalkorDB
        fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
        available = fdb.list_graphs()

        if group_id in available:
            db_name = group_id
        else:
            candidates = [g for g in available if g != "default_db"]
            if not candidates:
                logger.warning(f"No graphs found in FalkorDB for group_id={group_id}")
                return []
            db_name = candidates[0]
            logger.info(f"group_id '{group_id}' not found, using graph '{db_name}'")

        # Connect Graphiti to the specific graph database
        driver = FalkorDriver(host=FALKOR_HOST, port=FALKOR_PORT, database=db_name)
        graphiti_instance = Graphiti(graph_driver=driver)

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
    
    The KG contains agent-specific actions (posts, likes, comments) written
    by FalkorGraphMemoryUpdater during simulation, plus campaign entities.
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
    
    Reads profiles.json, enriches each profile, writes back.
    """
    profiles_path = os.path.join(sim_dir, "profiles.json")
    db_path = os.path.join(sim_dir, "oasis_simulation.db")

    if not os.path.exists(profiles_path):
        logger.warning(f"No profiles.json in {sim_dir}")
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
    state = _simulations.get(sim_id)
    sim_dir = state.output_dir if state else os.path.join(SIM_DIR, sim_id)

    if not os.path.isdir(sim_dir):
        raise HTTPException(404, f"Simulation {sim_id} not found")

    profiles_path = os.path.join(sim_dir, "profiles.json")
    if not os.path.exists(profiles_path):
        raise HTTPException(404, "No profiles.json found")

    # Determine group_id
    group_id = ""
    if state:
        group_id = state.group_id or sim_id
    else:
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if os.path.exists(config_path):
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

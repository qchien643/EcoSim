"""
Survey API — Post-simulation agent survey system.

Endpoints:
  POST /api/survey/create              — Create survey for simulation
  POST /api/survey/{id}/conduct        — Run survey (LLM asks agents)
  GET  /api/survey/{id}/results        — Get aggregated results
  GET  /api/survey/{id}/results/export  — Export as JSON
  GET  /api/survey/latest              — Find latest survey for a sim
"""
import json
import glob
import logging
import os
import re
import uuid
from collections import Counter
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from ecosim_common.agent_interview import (
    BUILTIN_LOADERS,
    INTENT_INFO_MAP,
    build_response_prompt,
    load_context_blocks,
)

logger = logging.getLogger("sim-svc.survey")

router = APIRouter(prefix="/api/survey", tags=["Survey"])

# ── Config ──
# apps/simulation/api/survey.py → api → simulation → apps → EcoSim
ECOSIM_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SIM_DIR = os.path.join(ECOSIM_ROOT, "data", "simulations")


def _sim_dir(sim_id: str) -> str:
    """Phase 10: resolve sim dir qua meta.db (nested layout
    `data/campaigns/<cid>/sims/<sid>/`). Fallback flat layout cũ."""
    try:
        from ecosim_common.path_resolver import resolve_simulation_paths
        p = resolve_simulation_paths(sim_id).get("sim_dir")
        if p:
            return p
    except Exception:
        pass
    return _sim_dir(sim_id)


# ── Request Models ──
class QuestionDef(BaseModel):
    text: str
    question_type: str = "open_ended"   # scale_1_10 | yes_no | open_ended | multiple_choice
    options: List[str] = []
    category: str = "general"            # general | sentiment | behavior | economic
    # Tier B+ redesign: explanation cho auto-generated questions
    rationale: str = ""
    # Tier B++ redesign: target Report section cho auto-gen questions
    # Values: executive | context | content | kpi | response | recommendation | ""
    report_section: str = ""

class CreateSurveyRequest(BaseModel):
    sim_id: str
    questions: Optional[List[QuestionDef]] = None

class GenerateQuestionsRequest(BaseModel):
    sim_id: str
    count: int = 10
    categories: Optional[List[str]] = None
    use_sentiment: bool = True
    use_crisis: bool = True


# ── Storage ──
_surveys: Dict[str, dict] = {}


# Canonical default questions — mirror apps/core/app/models/survey.py:DEFAULT_QUESTIONS
# (Sim service không import trực tiếp từ Core package; giữ duplicate data nhưng
# đảm bảo 5 câu giống nhau để /api/survey/default-questions consistent cả 2 bên.)
DEFAULT_QUESTIONS = [
    QuestionDef(
        text="Bạn đánh giá mức độ tác động của chiến dịch này đến hoạt động kinh doanh/tiêu dùng của bạn như thế nào?",
        question_type="scale_1_10",
        category="economic",
        report_section="kpi",
    ),
    QuestionDef(
        text="Bạn có thay đổi hành vi mua sắm/kinh doanh sau khi xảy ra biến cố không?",
        question_type="yes_no",
        options=["Yes", "No"],
        category="behavior",
        report_section="response",
    ),
    QuestionDef(
        text="Cảm nhận chung của bạn về chiến dịch này là gì?",
        question_type="multiple_choice",
        options=["Rất tích cực", "Tích cực", "Trung lập", "Tiêu cực", "Rất tiêu cực"],
        category="sentiment",
        report_section="response",
    ),
    QuestionDef(
        text="Theo bạn, đâu là rủi ro lớn nhất mà chiến dịch này có thể gặp phải?",
        question_type="open_ended",
        category="economic",
        report_section="recommendation",
    ),
    QuestionDef(
        text="Nếu có biến cố tương tự xảy ra trong tương lai, bạn sẽ phản ứng như thế nào?",
        question_type="open_ended",
        category="behavior",
        report_section="recommendation",
    ),
]


# ── Helpers ──
def _find_survey_on_disk(survey_id: str) -> Optional[dict]:
    """Search all sim dirs for a survey JSON file (Phase 10: nested layout)."""
    try:
        from ecosim_common.metadata_index import list_simulations
        sims = list_simulations()
    except Exception:
        sims = []
    for sim in sims:
        sid = sim.get("sid")
        if not sid:
            continue
        sim_dir = _sim_dir(sid)
        if not os.path.isdir(sim_dir):
            continue
        path = os.path.join(sim_dir, f"{survey_id}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                survey = json.load(f)
            _surveys[survey_id] = survey
            return survey
        # Also check survey_results.json
        results_path = os.path.join(sim_dir, "survey_results.json")
        if os.path.exists(results_path):
            with open(results_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("survey_id") == survey_id:
                _surveys[survey_id] = data
                return data
    return None


def _get_survey(survey_id: str) -> dict:
    """Get survey from memory or disk."""
    survey = _surveys.get(survey_id)
    if survey:
        return survey
    survey = _find_survey_on_disk(survey_id)
    if not survey:
        raise HTTPException(404, f"Survey {survey_id} not found")
    return survey


def _extract_number(text: str) -> Optional[float]:
    """Extract a number from an LLM answer text."""
    # Try direct number
    match = re.search(r'\b(\d+(?:\.\d+)?)\b', text)
    if match:
        val = float(match.group(1))
        if 1 <= val <= 10:
            return val
    return None


def _extract_yes_no(text: str) -> str:
    """Extract yes/no from an LLM answer text."""
    lower = text.lower().strip()
    if any(w in lower for w in ["yes", "có", "rồi", "chắc chắn", "đồng ý", "muốn"]):
        return "YES"
    if any(w in lower for w in ["no", "không", "chưa", "chẳng"]):
        return "NO"
    return "MAYBE"


def _aggregate_results(survey: dict) -> dict:
    """Aggregate raw responses into the format the frontend expects."""
    questions_map = {}
    for i, q in enumerate(survey.get("questions", [])):
        qid = f"q{i+1}"
        questions_map[qid] = {
            "question_id": qid,
            "question_text": q["text"],
            "question_type": q["question_type"],
            "category": q.get("category", "general"),
            "responses": [],
            "distribution": {},
            "average": None,
            "key_themes": [],
        }

    # Group responses by question
    for resp in survey.get("responses", []):
        q_text = resp.get("question")
        # Find matching question
        for qid, q_data in questions_map.items():
            if q_data["question_text"] == q_text:
                q_data["responses"].append({
                    "agent_name": resp.get("agent_name", "Unknown"),
                    "agent_role": resp.get("category", "participant"),
                    "answer": resp.get("answer", ""),
                    "reasoning": resp.get("reasoning", ""),
                })
                break

    # Compute aggregations per question
    for qid, q_data in questions_map.items():
        q_type = q_data["question_type"]
        answers = [r["answer"] for r in q_data["responses"]]

        if q_type in ("scale_1_10", "rating"):
            # Extract numeric values
            nums = [_extract_number(a) for a in answers]
            nums = [n for n in nums if n is not None]
            if nums:
                q_data["average"] = round(sum(nums) / len(nums), 1)
                # Distribution
                counter = Counter(int(n) for n in nums)
                q_data["distribution"] = dict(sorted(counter.items()))

        elif q_type == "yes_no":
            categories = [_extract_yes_no(a) for a in answers]
            q_data["distribution"] = dict(Counter(categories))

        elif q_type == "multiple_choice":
            q_data["distribution"] = dict(Counter(answers))

        elif q_type == "open_ended":
            # Extract key themes (simple word frequency)
            all_words = " ".join(answers).lower().split()
            stop_words = {"và", "là", "của", "cho", "các", "một", "này", "đã", "được", "với",
                          "the", "and", "to", "a", "of", "in", "for", "is", "that", "it", "i"}
            meaningful = [w for w in all_words if len(w) > 3 and w not in stop_words]
            top_words = Counter(meaningful).most_common(5)
            q_data["key_themes"] = [w for w, _ in top_words]

    # Build cross-analysis table
    cross_analysis = {}
    for resp in survey.get("responses", []):
        name = resp.get("agent_name", "Unknown")
        if name not in cross_analysis:
            cross_analysis[name] = {"role": resp.get("category", "participant")}
        # Find question ID
        for qid, q_data in questions_map.items():
            if q_data["question_text"] == resp.get("question"):
                answer = resp.get("answer", "")
                # Shorten for table
                if q_data["question_type"] in ("scale_1_10", "rating"):
                    num = _extract_number(answer)
                    cross_analysis[name][qid] = num if num else answer
                elif q_data["question_type"] == "yes_no":
                    cross_analysis[name][qid] = _extract_yes_no(answer)
                else:
                    cross_analysis[name][qid] = answer[:60] if len(answer) > 60 else answer
                break

    return {
        "survey_id": survey["survey_id"],
        "sim_id": survey["sim_id"],
        "total_respondents": survey.get("total_respondents", len(cross_analysis)),
        "questions": list(questions_map.values()),
        "cross_analysis": cross_analysis,
    }


# ── POST /api/survey/create ──
@router.post("/create")
async def create_survey(req: CreateSurveyRequest):
    """Create a survey for a completed simulation."""
    sim_dir = _sim_dir(req.sim_id)
    if not os.path.isdir(sim_dir):
        raise HTTPException(404, f"Simulation {req.sim_id} not found")

    survey_id = f"survey_{uuid.uuid4().hex[:8]}"
    questions = req.questions or DEFAULT_QUESTIONS

    survey = {
        "survey_id": survey_id,
        "sim_id": req.sim_id,
        "questions": [q.model_dump() for q in questions],
        "status": "created",
        "responses": [],
    }

    # Save to disk
    survey_path = os.path.join(sim_dir, f"{survey_id}.json")
    with open(survey_path, "w", encoding="utf-8") as f:
        json.dump(survey, f, indent=2, ensure_ascii=False)

    _surveys[survey_id] = survey

    return {
        "survey_id": survey_id,
        "sim_id": req.sim_id,
        "question_count": len(questions),
    }


# ── GET /api/survey/default-questions ── (Tier B+ redesign)
@router.get("/default-questions")
async def get_default_questions():
    """Return the canonical 5 default survey questions (unified schema).

    Mirror apps/core/app/models/survey.py:DEFAULT_QUESTIONS.
    Frontend / external tooling có thể prefetch list này để preview.
    """
    return {
        "count": len(DEFAULT_QUESTIONS),
        "questions": [q.model_dump() for q in DEFAULT_QUESTIONS],
    }


# ── POST /api/survey/generate-questions ── (Tier B+ redesign)
@router.post("/generate-questions")
async def generate_questions(req: GenerateQuestionsRequest):
    """LLM auto-sinh 8-12 câu hỏi khảo sát dựa trên sim context.

    Dùng cho cả:
    - Frontend SurveyView: user preview suggestions rồi edit/accept
    - Report pipeline: khi `auto_run_survey=true`, Report invoke endpoint này
      → sau đó auto-run `/create + /conduct` để populate survey_results.json
    """
    sim_dir = _sim_dir(req.sim_id)
    if not os.path.isdir(sim_dir):
        raise HTTPException(404, f"Simulation {req.sim_id} not found")

    # 1. Load campaign spec
    # campaign_id thường = sim_id hoặc prefix — scan spec file trong uploads
    campaign_spec: Dict = {}
    config_path = os.path.join(sim_dir, "simulation_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                sim_cfg = json.load(f)
            campaign_id = sim_cfg.get("campaign_id", "")
            if campaign_id:
                # Try uploads dir
                uploads_dir = os.path.join(ECOSIM_ROOT, "data", "uploads")
                spec_path = os.path.join(uploads_dir, f"{campaign_id}_spec.json")
                if os.path.exists(spec_path):
                    with open(spec_path, "r", encoding="utf-8") as f:
                        campaign_spec = json.load(f)
                else:
                    # Fallback: derive from simulation_config fields
                    campaign_spec = {
                        "name": sim_cfg.get("campaign_name", ""),
                        "campaign_type": sim_cfg.get("campaign_type", "other"),
                        "market": sim_cfg.get("campaign_market", ""),
                        "summary": sim_cfg.get("campaign_summary", ""),
                        "kpis": sim_cfg.get("kpis", []),
                        "identified_risks": sim_cfg.get("identified_risks", []),
                    }
        except Exception as e:
            logger.warning("Failed to load campaign spec for %s: %s", req.sim_id, e)

    if not campaign_spec:
        campaign_spec = {"name": "Unknown", "campaign_type": "other", "market": "VN"}

    # 2. Build sim_overview from actions.jsonl + profiles.json
    sim_overview: Dict = {}
    actions_path = os.path.join(sim_dir, "actions.jsonl")
    profiles_path = os.path.join(sim_dir, "profiles.json")
    try:
        if os.path.exists(actions_path):
            with open(actions_path, "r", encoding="utf-8") as f:
                action_lines = f.readlines()
            action_types = Counter()
            for line in action_lines:
                try:
                    a = json.loads(line)
                    atype = a.get("action_type", "")
                    if atype and atype not in ("sign_up", "refresh", "do_nothing"):
                        action_types[atype] += 1
                except json.JSONDecodeError:
                    pass
            sim_overview["action_types"] = dict(action_types)
            sim_overview["total_actions"] = sum(action_types.values())

        if os.path.exists(profiles_path):
            with open(profiles_path, "r", encoding="utf-8") as f:
                profiles = json.load(f)
            sim_overview["total_agents"] = len(profiles)
            mbti_dist = Counter(p.get("mbti", "?") for p in profiles)
            sim_overview["mbti_distribution"] = dict(mbti_dist)
    except Exception as e:
        logger.warning("Failed to build sim_overview for %s: %s", req.sim_id, e)

    # 3. Load sentiment summary (if requested + exists)
    # Phase 6.5: ưu tiên new path analysis/sentiment.json, fallback legacy.
    sentiment_summary: Optional[Dict] = None
    if req.use_sentiment:
        new_path = os.path.join(sim_dir, "analysis", "sentiment.json")
        legacy_path = os.path.join(sim_dir, "analysis_results.json")
        analysis_path = new_path if os.path.exists(new_path) else legacy_path
        if os.path.exists(analysis_path):
            try:
                with open(analysis_path, "r", encoding="utf-8") as f:
                    wrapper = json.load(f)
                sentiment_summary = wrapper.get("results", {}).get("sentiment")
            except Exception as e:
                logger.warning("Failed to load sentiment for %s: %s", req.sim_id, e)

    # 4. Load crisis events (if requested)
    crisis_events: List[Dict] = []
    if req.use_crisis:
        crisis_path = os.path.join(sim_dir, "crisis_scenarios.json")
        if os.path.exists(crisis_path):
            try:
                with open(crisis_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Extract events from scenarios
                if isinstance(data, list):
                    for sc in data:
                        if isinstance(sc, dict):
                            crisis_events.extend(sc.get("events", []) or [])
                elif isinstance(data, dict):
                    crisis_events = data.get("events", []) or []
            except Exception as e:
                logger.warning("Failed to load crisis for %s: %s", req.sim_id, e)

    # 5. Invoke generator (uses ecosim_common.LLMClient)
    try:
        from ecosim_common.survey_question_gen import generate_survey_questions
        questions = generate_survey_questions(
            campaign_spec=campaign_spec,
            sim_overview=sim_overview,
            sentiment_summary=sentiment_summary,
            crisis_events=crisis_events,
            count=req.count,
            categories=req.categories,
        )
    except Exception as e:
        logger.error("SurveyQuestionGenerator failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Question generation failed: {e}")

    # 6. Save artifact (for caching + Report pipeline to read)
    saved_path = os.path.join(sim_dir, "suggested_questions.json")
    try:
        from ecosim_common.atomic_io import atomic_write_json
        atomic_write_json(saved_path, {
            "sim_id": req.sim_id,
            "count": len(questions),
            "params": req.model_dump(),
            "questions": questions,
        })
    except Exception as e:
        logger.warning("Failed to save suggested_questions.json: %s", e)

    return {
        "sim_id": req.sim_id,
        "count": len(questions),
        "questions": questions,
        "saved_to": saved_path,
    }


# ── GET /api/survey/latest ── (must come before /{survey_id} routes)
@router.get("/latest")
async def get_latest_survey(
    sim_id: str = Query("", description="Simulation ID"),
):
    """Find the latest survey for a simulation."""
    if not sim_id:
        raise HTTPException(400, "sim_id is required")

    sim_dir = _sim_dir(sim_id)
    if not os.path.isdir(sim_dir):
        raise HTTPException(404, f"Simulation {sim_id} not found")

    # Check survey_results.json first (aggregated, preferred)
    results_path = os.path.join(sim_dir, "survey_results.json")
    if os.path.exists(results_path):
        with open(results_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sid = data.get("survey_id", "")
        if sid:
            _surveys[sid] = data
        return {"found": True, "survey_id": sid, "results": data}

    # Check for individual survey files
    survey_files = sorted(glob.glob(os.path.join(sim_dir, "survey_*.json")), reverse=True)
    for sf in survey_files:
        with open(sf, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("status") == "completed":
            sid = data.get("survey_id", "")
            _surveys[sid] = data
            aggregated = _aggregate_results(data)
            return {"found": True, "survey_id": sid, "results": aggregated}

    return {"found": False, "survey_id": "", "results": None}


# ── Survey ↔ Interview intent mapping (rule-based, no LLM call) ──

def _map_question_to_intent(q: dict) -> str:
    """Map a survey question's (category, report_section) → canonical interview intent.

    Used to select context blocks for the 2-phase interview flow without
    spending an LLM classification call per question.
    """
    cat = str(q.get("category", "") or "").lower()
    sec = str(q.get("report_section", "") or "").lower()
    if sec == "response" or cat == "sentiment":
        return "opinion_campaign"
    if sec == "content" or cat == "behavior":
        return "motivation"
    if sec == "kpi":
        return "projection"
    if sec == "context":
        return "identity"
    if sec == "recommendation":
        return "projection"
    return "general"


def _format_hint_for(q: dict) -> str:
    q_type = q.get("question_type", "open_ended")
    if q_type in ("scale_1_10", "rating"):
        return "Respond with ONLY a number from 1 to 10, followed by a brief reason."
    if q_type == "yes_no":
        return "Respond with YES or NO first, then a brief reason."
    if q_type == "multiple_choice":
        opts = ", ".join(q.get("options", []) or [])
        return f"Choose ONE of: [{opts}], then give a brief reason."
    return "Respond in 1-3 sentences."


# ── POST /api/survey/{survey_id}/conduct ──
@router.post("/{survey_id}/conduct")
async def conduct_survey(survey_id: str):
    """Conduct the survey via the shared 2-phase interview flow.

    For each agent × question:
      1. Map question → canonical intent (rule-based, free).
      2. Load selective context blocks once per (agent, intent) pair.
      3. Compose in-character system prompt via `build_response_prompt`.
      4. Ask the LLM (fast model) the question with a format-specific rule.
    """
    survey = _get_survey(survey_id)

    sim_id = survey["sim_id"]
    sim_dir = _sim_dir(sim_id)

    # Load agent profiles
    profiles_path = os.path.join(sim_dir, "profiles.json")
    if not os.path.exists(profiles_path):
        raise HTTPException(400, f"No profiles found for simulation {sim_id}")

    with open(profiles_path, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    # LLM config — Phase 3 answers go to the fast model to save cost.
    import httpx
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    fast_model = (
        os.environ.get("LLM_FAST_MODEL_NAME", "").strip()
        or os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")
    )

    questions = list(survey["questions"])
    # Precompute intent per question (shared across all agents)
    q_intents = [_map_question_to_intent(q) for q in questions]

    all_responses = []
    logger.info(
        "Conducting survey %s: %d agents × %d questions (model=%s)",
        survey_id, len(profiles), len(questions), fast_model,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        for pi, profile in enumerate(profiles):
            agent_name = profile.get("realname", profile.get("username", f"Agent_{pi}"))
            agent_role = profile.get("role", "participant")

            # Cache context-block payloads per intent for this agent
            intent_blocks_cache: Dict[str, Dict[str, str]] = {}

            for qi, q in enumerate(questions):
                intent_name = q_intents[qi]
                if intent_name not in intent_blocks_cache:
                    required_blocks = INTENT_INFO_MAP.get(
                        intent_name, INTENT_INFO_MAP["general"]
                    )
                    intent_blocks_cache[intent_name] = load_context_blocks(
                        profile,
                        required_blocks,
                        loaders_registry=BUILTIN_LOADERS,
                        topic_hint="",
                    )
                context_blocks = intent_blocks_cache[intent_name]

                intent_data = {
                    "intent": intent_name,
                    "language": "vi",  # survey questions default to Vietnamese
                }

                format_hint = _format_hint_for(q)
                system_prompt = build_response_prompt(
                    profile,
                    intent_data,
                    context_blocks,
                    extra_rules=[
                        "This is a survey response. Follow the format instruction in the "
                        "user message exactly (scale = integer 1-10; yes_no = YES|NO; "
                        "multiple_choice = one of the listed options), then add a brief "
                        "reason in the same turn.",
                    ],
                )

                user_msg = (
                    f"Survey question: {q['text']}\n"
                    f"Format: {format_hint}"
                )

                try:
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": fast_model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_msg},
                            ],
                            "max_tokens": 200,
                            "temperature": 0.7,
                        },
                    )
                    resp.raise_for_status()
                    answer = resp.json()["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    logger.warning(
                        "LLM call failed for %s/q%d: %s", agent_name, qi + 1, e,
                    )
                    answer = f"[Error: {e}]"

                all_responses.append({
                    "agent_name": agent_name,
                    "agent_role": agent_role,
                    "question": q["text"],
                    "question_type": q.get("question_type", "open_ended"),
                    "category": q.get("category", "general"),
                    "report_section": q.get("report_section", ""),
                    "intent": intent_name,
                    "answer": answer,
                })

            logger.info("  Agent %d/%d: %s done", pi + 1, len(profiles), agent_name)

    survey["responses"] = all_responses
    survey["status"] = "completed"
    survey["total_respondents"] = len(profiles)

    # Save raw survey + aggregated results
    raw_path = os.path.join(sim_dir, f"{survey_id}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(survey, f, indent=2, ensure_ascii=False)

    # Also save aggregated results as survey_results.json (for quick load)
    aggregated = _aggregate_results(survey)
    results_path = os.path.join(sim_dir, "survey_results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(aggregated, f, indent=2, ensure_ascii=False)

    _surveys[survey_id] = survey
    logger.info(f"Survey {survey_id} completed: {len(profiles)} agents, {len(all_responses)} responses")

    return {
        "survey_id": survey_id,
        "status": "completed",
        "total_respondents": len(profiles),
        "total_responses": len(all_responses),
    }


# ── GET /api/survey/{survey_id}/results ──
@router.get("/{survey_id}/results")
async def get_results(survey_id: str):
    """Get aggregated survey results."""
    survey = _get_survey(survey_id)

    if survey.get("status") != "completed":
        return survey  # Return raw if not completed yet

    # Check if we have pre-aggregated results in survey_results.json
    sim_dir = _sim_dir(survey["sim_id"])
    results_path = os.path.join(sim_dir, "survey_results.json")
    if os.path.exists(results_path):
        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Otherwise aggregate on the fly
    return _aggregate_results(survey)


# ── GET /api/survey/{survey_id}/results/export ──
@router.get("/{survey_id}/results/export")
async def export_results(survey_id: str):
    """Export survey results as downloadable JSON."""
    survey = _get_survey(survey_id)

    aggregated = _aggregate_results(survey) if survey.get("status") == "completed" else survey
    content = json.dumps(aggregated, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=survey_{survey_id}.json"},
    )


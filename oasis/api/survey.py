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

logger = logging.getLogger("sim-svc.survey")

router = APIRouter(prefix="/api/survey", tags=["Survey"])

# ── Config ──
ECOSIM_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SIM_DIR = os.path.join(ECOSIM_ROOT, "data", "simulations")


# ── Request Models ──
class QuestionDef(BaseModel):
    text: str
    question_type: str = "open_ended"
    options: List[str] = []
    category: str = "general"

class CreateSurveyRequest(BaseModel):
    sim_id: str
    questions: Optional[List[QuestionDef]] = None


# ── Storage ──
_surveys: Dict[str, dict] = {}


# Default survey questions — designed for economic campaign evaluation (Vietnamese)
DEFAULT_QUESTIONS = [
    QuestionDef(
        text="Bạn đánh giá mức độ hiệu quả của chiến dịch này như thế nào? (1-10)",
        question_type="scale_1_10",
        category="satisfaction",
    ),
    QuestionDef(
        text="Sản phẩm/dịch vụ nào trong chiến dịch thu hút bạn nhất?",
        question_type="open_ended",
        category="product_interest",
    ),
    QuestionDef(
        text="Bạn có muốn giới thiệu chiến dịch này cho người khác không?",
        question_type="yes_no",
        options=["Yes", "No"],
        category="nps",
    ),
    QuestionDef(
        text="Điều gì cần được cải thiện trong các chiến dịch tương tự?",
        question_type="open_ended",
        category="feedback",
    ),
    QuestionDef(
        text="Bạn cảm thấy chiến dịch này tác động đến quyết định mua hàng của bạn ở mức nào? (1-10)",
        question_type="scale_1_10",
        category="purchase_intent",
    ),
]


# ── Helpers ──
def _find_survey_on_disk(survey_id: str) -> Optional[dict]:
    """Search all sim dirs for a survey JSON file."""
    for sim_name in os.listdir(SIM_DIR):
        sim_dir = os.path.join(SIM_DIR, sim_name)
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
    sim_dir = os.path.join(SIM_DIR, req.sim_id)
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


# ── GET /api/survey/latest ── (must come before /{survey_id} routes)
@router.get("/latest")
async def get_latest_survey(
    sim_id: str = Query("", description="Simulation ID"),
):
    """Find the latest survey for a simulation."""
    if not sim_id:
        raise HTTPException(400, "sim_id is required")

    sim_dir = os.path.join(SIM_DIR, sim_id)
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


# ── POST /api/survey/{survey_id}/conduct ──
@router.post("/{survey_id}/conduct")
async def conduct_survey(survey_id: str):
    """Conduct the survey: LLM asks each agent each question."""
    survey = _get_survey(survey_id)

    sim_id = survey["sim_id"]
    sim_dir = os.path.join(SIM_DIR, sim_id)

    # Load agent profiles
    profiles_path = os.path.join(sim_dir, "profiles.json")
    if not os.path.exists(profiles_path):
        raise HTTPException(400, f"No profiles found for simulation {sim_id}")

    with open(profiles_path, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    # LLM config
    import httpx
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")

    all_responses = []
    logger.info(f"Conducting survey {survey_id}: {len(profiles)} agents × {len(survey['questions'])} questions")

    for pi, profile in enumerate(profiles):
        agent_name = profile.get("realname", profile.get("username", f"Agent_{pi}"))
        persona = profile.get("persona", "A consumer")
        agent_role = profile.get("role", "participant")

        for q in survey["questions"]:
            q_type = q["question_type"]

            # Build format instruction
            if q_type in ("scale_1_10", "rating"):
                format_hint = "Answer with ONLY a number from 1 to 10, followed by a brief reason."
            elif q_type == "yes_no":
                format_hint = "Answer with YES or NO first, then a brief reason."
            else:
                format_hint = "Answer in 1-3 sentences."

            prompt = (
                f"You are {agent_name}. {persona}\n"
                f"You just participated in an economic campaign simulation.\n\n"
                f"Survey question: {q['text']}\n"
                f"Instructions: {format_hint}\n"
                f"Answer (in character, Vietnamese preferred):"
            )

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 200,
                            "temperature": 0.7,
                        },
                    )
                    resp.raise_for_status()
                    answer = resp.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.warning(f"LLM call failed for {agent_name}/q{survey['questions'].index(q)+1}: {e}")
                answer = f"[Error: {e}]"

            all_responses.append({
                "agent_name": agent_name,
                "agent_role": agent_role,
                "question": q["text"],
                "question_type": q_type,
                "category": q.get("category", "general"),
                "answer": answer,
            })

        logger.info(f"  Agent {pi+1}/{len(profiles)}: {agent_name} done")

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
    sim_dir = os.path.join(SIM_DIR, survey["sim_id"])
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


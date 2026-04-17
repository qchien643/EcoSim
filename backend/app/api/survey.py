"""
Survey API — Post-simulation agent survey system.

E2E Flow:
  POST /api/survey/create         → Create survey with questions
  POST /api/survey/{id}/conduct   → Run survey on agents (LLM calls)
  GET  /api/survey/{id}/results   → Get aggregated results
  GET  /api/survey/{id}/results/export → Export as JSON
"""

import json
import logging

from flask import Blueprint, jsonify, request

from ..models.simulation import SimStatus
from ..models.survey import QuestionType, SurveyQuestion
from ..services.sim_manager import SimManager
from ..services.survey_engine import SurveyEngine

logger = logging.getLogger("ecosim.api.survey")

survey_bp = Blueprint("survey", __name__, url_prefix="/api/survey")

sim_manager = SimManager()
survey_engine = SurveyEngine()


@survey_bp.route("/default-questions", methods=["GET"])
def get_default_questions():
    """Return the default survey questions for the frontend 'Generate Sample' button."""
    from ..services.survey_engine import DEFAULT_QUESTIONS
    return jsonify({
        "questions": [q.model_dump(mode="json") for q in DEFAULT_QUESTIONS],
    })


@survey_bp.route("/create", methods=["POST"])
def create_survey():
    """Create a survey for a completed simulation.

    Request JSON:
        sim_id: str (required, must be COMPLETED)
        questions: list[dict] (optional, uses defaults if not provided)
            Each question: {text, question_type, options?, category?}
    """
    data = request.get_json() or {}
    sim_id = data.get("sim_id", "")

    if not sim_id:
        return jsonify({"error": "sim_id is required"}), 400

    state = sim_manager.get(sim_id)
    if not state:
        return jsonify({"error": f"Simulation {sim_id} not found"}), 404

    if state.status != SimStatus.COMPLETED:
        return jsonify({
            "error": f"Simulation must be COMPLETED, current: {state.status.value}"
        }), 400

    # Parse custom questions if provided
    questions = None
    if "questions" in data:
        questions = []
        for i, q in enumerate(data["questions"]):
            questions.append(SurveyQuestion(
                id=q.get("id", f"q{i+1}"),
                text=q["text"],
                question_type=QuestionType(q.get("question_type", "open_ended")),
                options=q.get("options", []),
                category=q.get("category", "general"),
            ))

    num_agents = data.get("num_agents")  # None = all agents
    include_sim_context = data.get("include_sim_context", True)

    survey = survey_engine.create_survey(
        sim_id, questions,
        num_agents=num_agents,
        include_sim_context=include_sim_context,
    )

    return jsonify({
        "survey_id": survey.survey_id,
        "sim_id": sim_id,
        "question_count": len(survey.questions),
        "questions": [q.model_dump() for q in survey.questions],
    }), 201


@survey_bp.route("/<survey_id>/conduct", methods=["POST"])
def conduct_survey(survey_id: str):
    """Conduct the survey: LLM asks each agent each question.

    This may take a while (agents × questions × LLM calls).
    """
    try:
        results = survey_engine.conduct_survey(survey_id)

        return jsonify({
            "survey_id": survey_id,
            "status": "completed",
            "total_respondents": results.total_respondents,
            "questions_answered": len(results.questions),
            "summary": [
                {
                    "question_id": q.question_id,
                    "question_text": q.question_text[:80],
                    "type": q.question_type,
                    "responses": len(q.responses),
                    "average": q.average,
                    "distribution": q.distribution,
                    "key_themes": q.key_themes,
                }
                for q in results.questions
            ],
        }), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Survey conduct failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@survey_bp.route("/<survey_id>/results", methods=["GET"])
def get_results(survey_id: str):
    """Get full survey results with all responses and cross-analysis."""
    results = survey_engine.get_results(survey_id)
    if not results:
        return jsonify({"error": f"Results for survey {survey_id} not found"}), 404

    return jsonify(results.model_dump(mode="json"))


@survey_bp.route("/<survey_id>/results/export", methods=["GET"])
def export_results(survey_id: str):
    """Export survey results as downloadable JSON."""
    results = survey_engine.get_results(survey_id)
    if not results:
        return jsonify({"error": f"Results for survey {survey_id} not found"}), 404

    # Format for export
    export = {
        "survey_id": results.survey_id,
        "sim_id": results.sim_id,
        "total_respondents": results.total_respondents,
        "questions": [],
    }

    for q in results.questions:
        q_export = {
            "id": q.question_id,
            "text": q.question_text,
            "type": q.question_type,
            "summary": {},
            "responses": [],
        }

        if q.average is not None:
            q_export["summary"]["average"] = q.average
            q_export["summary"]["min"] = q.min_val
            q_export["summary"]["max"] = q.max_val
        if q.distribution:
            q_export["summary"]["distribution"] = q.distribution
        if q.key_themes:
            q_export["summary"]["key_themes"] = q.key_themes

        for r in q.responses:
            q_export["responses"].append({
                "agent_name": r.agent_name,
                "agent_role": r.agent_role,
                "answer": r.answer,
                "reasoning": r.reasoning,
            })

        export["questions"].append(q_export)

    export["cross_analysis"] = results.cross_analysis

    from flask import Response
    return Response(
        json.dumps(export, ensure_ascii=False, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=survey_{survey_id}.json"},
    )

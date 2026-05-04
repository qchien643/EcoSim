"""
Report API — Enterprise-grade report generation with ReACT agent.

Endpoints:
  POST /api/report/generate          — Start report generation
  GET  /api/report/<sim_id>          — Get full report
  GET  /api/report/<sim_id>/outline  — Get report outline
  GET  /api/report/<sim_id>/section/<idx> — Get specific section
  GET  /api/report/<sim_id>/progress — Get generation progress
  POST /api/report/<sim_id>/chat     — Post-report Q&A chat
"""

import json
import logging
import os

from flask import Blueprint, jsonify, request

from ..config import Config
from ..services.report_agent import ReportAgent
from ..services.sim_manager import SimManager
from ..models.simulation import SimStatus

logger = logging.getLogger("ecosim.api.report")

report_bp = Blueprint("report", __name__, url_prefix="/api/report")

sim_manager = SimManager()


def _sim_dir_from_meta(sim_id: str) -> str:
    """Resolve sim folder via meta.db.

    Phase 10 moved sims to `data/campaigns/<cid>/sims/<sid>/`. The legacy
    flat layout `Config.SIM_DIR/<sim_id>/` no longer exists, so this
    endpoint family must look up the canonical directory in meta.db.
    """
    try:
        from ecosim_common.path_resolver import resolve_simulation_paths
        return resolve_simulation_paths(sim_id, fallback=True).get("sim_dir") or ""
    except Exception as e:
        logger.warning("resolve_simulation_paths(%s) fail: %s", sim_id, e)
        return os.path.join(Config.SIM_DIR, sim_id)


@report_bp.route("/generate", methods=["POST"])
def generate_report():
    """Generate economic analysis report for a completed simulation.

    Body (all optional except sim_id):
        sim_id (str, required)
        campaign_id (str): override; default lấy từ SimState
        auto_run_sentiment (bool, default True): nếu chưa có analysis_results.json
            thì auto-invoke CampaignReportGenerator trong preflight (zero API cost)
        auto_run_survey (bool, default False): explicit opt-in — hiện chưa
            auto-run vì tốn N_agents × N_questions LLM calls
        survey_id (str): pin specific survey. Empty → Report pick latest.
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

    auto_run_sentiment = bool(data.get("auto_run_sentiment", True))
    auto_run_survey = bool(data.get("auto_run_survey", False))
    survey_id = str(data.get("survey_id", "") or "")
    campaign_id_override = str(data.get("campaign_id", "") or "") or state.campaign_id

    try:
        # Sim graph name = "sim_<sim_id>" (master+fork architecture).
        graph_name = sim_id if sim_id.startswith("sim_") else f"sim_{sim_id}"
        agent = ReportAgent(graph_name=graph_name)
        result = agent.generate(
            sim_id,
            campaign_id=campaign_id_override,
            auto_run_sentiment=auto_run_sentiment,
            auto_run_survey=auto_run_survey,
            survey_id=survey_id,
        )

        return jsonify({
            "sim_id": sim_id,
            "status": "generated",
            "report_id": result.get("report_id"),
            "report_path": result["report_path"],
            "report_length": result["report_length"],
            "sections_count": result.get("sections_count", 0),
            "total_tool_calls": result.get("total_tool_calls", 0),
            "total_evidence": result.get("total_evidence", 0),
            "duration_s": result.get("duration_s", 0),
            "tool_results_summary": result.get("tool_results_summary", {}),
        }), 200

    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@report_bp.route("/<sim_id>", methods=["GET"])
def get_report(sim_id: str):
    """Get the full generated report (paths via meta.db)."""
    sim_dir = _sim_dir_from_meta(sim_id)

    # Try new path first, then legacy `report.md` at sim root
    report_path = os.path.join(sim_dir, "report", "full_report.md")
    if not os.path.exists(report_path):
        report_path = os.path.join(sim_dir, "report.md")

    if not os.path.exists(report_path):
        return jsonify({"error": "Report not generated yet"}), 404

    with open(report_path, "r", encoding="utf-8") as f:
        report_md = f.read()

    # Load meta if available
    meta = {}
    meta_path = os.path.join(sim_dir, "report", "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    return jsonify({
        "sim_id": sim_id,
        "report_md": report_md,
        "report_length": len(report_md),
        "meta": meta,
    })


@report_bp.route("/<sim_id>/outline", methods=["GET"])
def get_outline(sim_id: str):
    """Get the report outline (paths via meta.db)."""
    outline_path = os.path.join(_sim_dir_from_meta(sim_id), "report", "outline.json")
    if not os.path.exists(outline_path):
        return jsonify({"error": "Outline not available"}), 404

    with open(outline_path, "r", encoding="utf-8") as f:
        outline = json.load(f)

    return jsonify({"sim_id": sim_id, "outline": outline})


@report_bp.route("/<sim_id>/section/<int:idx>", methods=["GET"])
def get_section(sim_id: str, idx: int):
    """Get a specific report section (1-indexed). Paths via meta.db."""
    section_path = os.path.join(
        _sim_dir_from_meta(sim_id), "report", f"section_{idx:02d}.md"
    )
    if not os.path.exists(section_path):
        return jsonify({"error": f"Section {idx} not found"}), 404

    with open(section_path, "r", encoding="utf-8") as f:
        content = f.read()

    return jsonify({"sim_id": sim_id, "section_index": idx, "content": content})


@report_bp.route("/<sim_id>/progress", methods=["GET"])
def get_progress(sim_id: str):
    """Get report generation progress (paths via meta.db)."""
    progress_path = os.path.join(
        _sim_dir_from_meta(sim_id), "report", "progress.json"
    )
    if not os.path.exists(progress_path):
        return jsonify({"status": "not_started", "message": "Report not started"}), 200

    with open(progress_path, "r", encoding="utf-8") as f:
        progress = json.load(f)

    return jsonify({"sim_id": sim_id, **progress})


@report_bp.route("/<sim_id>/chat", methods=["POST"])
def chat_report(sim_id: str):
    """Post-report Q&A chat."""
    data = request.get_json() or {}
    message = data.get("message", "")
    chat_history = data.get("history", [])

    if not message:
        return jsonify({"error": "message is required"}), 400

    try:
        graph_name = sim_id if sim_id.startswith("sim_") else f"sim_{sim_id}"
        agent = ReportAgent(graph_name=graph_name)
        result = agent.chat(sim_id, message, chat_history)
        return jsonify({"sim_id": sim_id, **result})
    except Exception as e:
        logger.error(f"Chat failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

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


@report_bp.route("/generate", methods=["POST"])
def generate_report():
    """Generate economic analysis report for a completed simulation."""
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

    try:
        agent = ReportAgent()
        result = agent.generate(sim_id, campaign_id=state.campaign_id)

        return jsonify({
            "sim_id": sim_id,
            "status": "generated",
            "report_id": result.get("report_id"),
            "report_path": result["report_path"],
            "report_length": result["report_length"],
            "sections_count": result.get("sections_count", 0),
            "total_tool_calls": result.get("total_tool_calls", 0),
            "duration_s": result.get("duration_s", 0),
            "tool_results_summary": result.get("tool_results_summary", {}),
        }), 200

    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@report_bp.route("/<sim_id>", methods=["GET"])
def get_report(sim_id: str):
    """Get the full generated report."""
    sim_dir = os.path.join(Config.SIM_DIR, sim_id)

    # Try new path first, then legacy
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
    """Get the report outline."""
    outline_path = os.path.join(Config.SIM_DIR, sim_id, "report", "outline.json")
    if not os.path.exists(outline_path):
        return jsonify({"error": "Outline not available"}), 404

    with open(outline_path, "r", encoding="utf-8") as f:
        outline = json.load(f)

    return jsonify({"sim_id": sim_id, "outline": outline})


@report_bp.route("/<sim_id>/section/<int:idx>", methods=["GET"])
def get_section(sim_id: str, idx: int):
    """Get a specific report section (1-indexed)."""
    section_path = os.path.join(Config.SIM_DIR, sim_id, "report", f"section_{idx:02d}.md")
    if not os.path.exists(section_path):
        return jsonify({"error": f"Section {idx} not found"}), 404

    with open(section_path, "r", encoding="utf-8") as f:
        content = f.read()

    return jsonify({"sim_id": sim_id, "section_index": idx, "content": content})


@report_bp.route("/<sim_id>/progress", methods=["GET"])
def get_progress(sim_id: str):
    """Get report generation progress."""
    progress_path = os.path.join(Config.SIM_DIR, sim_id, "report", "progress.json")
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
        agent = ReportAgent()
        result = agent.chat(sim_id, message, chat_history)
        return jsonify({"sim_id": sim_id, **result})
    except Exception as e:
        logger.error(f"Chat failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

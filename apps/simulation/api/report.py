"""
Report API — Campaign Effectiveness Analysis.

Endpoints:
  GET  /api/analysis/summary      — Full campaign report (metrics + sentiment + score)
  GET  /api/analysis/sentiment    — Sentiment analysis of all comments
  GET  /api/analysis/per-round    — Round-by-round breakdown
  GET  /api/analysis/score        — Campaign effectiveness score
  POST /api/analysis/save         — Save analysis results to sim directory
  GET  /api/analysis/cached       — Load previously saved results
"""
import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Body

logger = logging.getLogger("sim-svc.report")

router = APIRouter(prefix="/api/analysis", tags=["Campaign Analysis"])

# apps/simulation/api/report.py → api → simulation → apps → EcoSim
ECOSIM_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.path.join(ECOSIM_ROOT, "data")
SIMS_DIR = os.path.join(DATA_DIR, "simulations")

DB_NAMES = ["oasis_simulation.db", "sim.db", "simulation.db"]


def _find_db_in_dir(sim_dir: str) -> str | None:
    """Return the first DB file found in a sim directory, or None."""
    for name in DB_NAMES:
        db = os.path.join(sim_dir, name)
        if os.path.exists(db):
            return db
    return None


def _find_sim_db(sim_id: str = "") -> str:
    """Find the simulation database path."""
    # Specific sim_id requested
    if sim_id:
        for prefix in ["", "sim_"]:
            d = os.path.join(SIMS_DIR, f"{prefix}{sim_id}")
            if os.path.isdir(d):
                db = _find_db_in_dir(d)
                if db:
                    return db

    # Fallback: scan all sim dirs for latest one with a DB
    if os.path.isdir(SIMS_DIR):
        dirs = sorted(os.listdir(SIMS_DIR), reverse=True)
        for d in dirs:
            full = os.path.join(SIMS_DIR, d)
            if os.path.isdir(full):
                db = _find_db_in_dir(full)
                if db:
                    return db

    raise HTTPException(404, "No simulation database found in any directory")


def _find_actions(sim_id: str = "") -> str:
    """Find actions.jsonl path."""
    # If sim_id is given, try its directory
    if sim_id:
        for prefix in ["", "sim_"]:
            p = os.path.join(SIMS_DIR, f"{prefix}{sim_id}", "actions.jsonl")
            if os.path.exists(p):
                return p

    # Fallback: same dir as the DB
    try:
        db_path = _find_sim_db(sim_id)
        sim_dir = os.path.dirname(db_path)
        p = os.path.join(sim_dir, "actions.jsonl")
        if os.path.exists(p):
            return p
    except Exception:
        pass
    return ""


@router.get("/simulations")
async def list_simulations():
    """List available simulation directories that have a database."""
    results = []
    if os.path.isdir(SIMS_DIR):
        for d in sorted(os.listdir(SIMS_DIR), reverse=True):
            full = os.path.join(SIMS_DIR, d)
            if os.path.isdir(full):
                db = _find_db_in_dir(full)
                has_actions = os.path.exists(os.path.join(full, "actions.jsonl"))
                results.append({
                    "sim_id": d,
                    "has_db": db is not None,
                    "has_actions": has_actions,
                })
    return {"simulations": results}


@router.get("/summary")
async def get_report_summary(
    sim_id: str = Query("", description="Simulation ID"),
    num_rounds: int = Query(1, description="Number of rounds in simulation"),
):
    """Full campaign effectiveness report."""
    try:
        from sentiment_analyzer import CampaignReportGenerator

        db_path = _find_sim_db(sim_id)
        actions_path = _find_actions(sim_id)

        gen = CampaignReportGenerator(db_path, actions_path)
        report = gen.generate_full_report(num_rounds)
        report["sim_db"] = db_path

        # Auto-save results to the sim directory
        sim_dir = os.path.dirname(db_path)
        _save_analysis_to_dir(sim_dir, report)

        return report

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis summary failed: {e}", exc_info=True)
        raise HTTPException(500, detail=f"Analysis failed: {type(e).__name__}: {str(e)}")


def _save_analysis_to_dir(sim_dir: str, data: dict):
    """Save analysis results as JSON in the simulation directory."""
    try:
        save_data = {
            "timestamp": datetime.now().isoformat(),
            "results": data,
        }
        path = os.path.join(sim_dir, "analysis_results.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Analysis results saved to {path}")
    except Exception as e:
        logger.warning(f"Failed to save analysis results: {e}")


@router.post("/save")
async def save_analysis(
    sim_id: str = Query("", description="Simulation ID"),
    data: dict = Body(..., description="Analysis results to save"),
):
    """Save analysis results to the simulation directory."""
    db_path = _find_sim_db(sim_id)
    sim_dir = os.path.dirname(db_path)
    _save_analysis_to_dir(sim_dir, data)
    return {"status": "saved", "sim_dir": sim_dir}


@router.get("/cached")
async def get_cached_analysis(
    sim_id: str = Query("", description="Simulation ID"),
):
    """Load previously saved analysis results."""
    db_path = _find_sim_db(sim_id)
    sim_dir = os.path.dirname(db_path)
    path = os.path.join(sim_dir, "analysis_results.json")

    if not os.path.exists(path):
        return {"cached": False, "results": None}

    with open(path, "r", encoding="utf-8") as f:
        saved = json.load(f)

    return {
        "cached": True,
        "timestamp": saved.get("timestamp"),
        "results": saved.get("results"),
    }


@router.get("/sentiment")
async def get_sentiment_analysis(
    sim_id: str = Query("", description="Simulation ID"),
):
    """Sentiment analysis of all simulation comments."""
    from sentiment_analyzer import CampaignReportGenerator

    db_path = _find_sim_db(sim_id)
    gen = CampaignReportGenerator(db_path)
    return gen.analyze_comment_sentiment()


@router.get("/per-round")
async def get_per_round_metrics(
    sim_id: str = Query("", description="Simulation ID"),
):
    """Round-by-round metrics breakdown."""
    from sentiment_analyzer import CampaignReportGenerator

    db_path = _find_sim_db(sim_id)
    actions_path = _find_actions(sim_id)

    if not actions_path:
        raise HTTPException(404, "actions.jsonl not found")

    gen = CampaignReportGenerator(db_path, actions_path)
    return {"rounds": gen.get_per_round_metrics()}


@router.get("/score")
async def get_campaign_score(
    sim_id: str = Query("", description="Simulation ID"),
    num_rounds: int = Query(1, description="Number of rounds"),
):
    """Calculate campaign effectiveness score [0-1]."""
    from sentiment_analyzer import CampaignReportGenerator

    db_path = _find_sim_db(sim_id)
    actions_path = _find_actions(sim_id)

    gen = CampaignReportGenerator(db_path, actions_path)
    return gen.generate_campaign_score(num_rounds)

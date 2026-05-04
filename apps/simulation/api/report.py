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


def _sim_paths(sim_id: str) -> dict:
    """Resolve all sim file paths from meta.db.

    Phase 10 moved sims under `data/campaigns/<cid>/sims/<sid>/`. The old
    `data/simulations/<sid>/` flat layout no longer exists. Always go through
    meta.db so `oasis_db_path` / `actions_path` point at the right place.
    """
    try:
        from ecosim_common.path_resolver import resolve_simulation_paths
        return dict(resolve_simulation_paths(sim_id, fallback=True))
    except Exception:
        return {}


def _find_sim_db(sim_id: str = "") -> str:
    """Resolve OASIS SQLite path via meta.db."""
    if not sim_id:
        # Fallback: pick the most recently accessed completed sim from meta.db
        try:
            from ecosim_common.metadata_index import list_simulations as _ls
            for s in _ls(limit=50) or []:
                p = (s.get("oasis_db_path") or "").strip()
                if p and os.path.exists(p):
                    return p
        except Exception:
            pass
        raise HTTPException(404, "No simulation database found in meta.db")
    p = _sim_paths(sim_id).get("oasis_db_path") or ""
    if p and os.path.exists(p):
        return p
    raise HTTPException(404, f"No DB for sim {sim_id}")


def _find_actions(sim_id: str = "") -> str:
    """Resolve actions.jsonl path via meta.db."""
    if not sim_id:
        # Same fallback strategy as _find_sim_db
        try:
            from ecosim_common.metadata_index import list_simulations as _ls
            for s in _ls(limit=50) or []:
                p = (s.get("actions_path") or "").strip()
                if p and os.path.exists(p):
                    return p
        except Exception:
            pass
        return ""
    return _sim_paths(sim_id).get("actions_path") or ""


@router.get("/simulations")
async def list_simulations():
    """List available simulations + which artifacts each one has on disk."""
    results = []
    try:
        from ecosim_common.metadata_index import list_simulations as _ls
        for s in _ls(limit=200) or []:
            sid = s.get("sid") or ""
            db_p = s.get("oasis_db_path") or ""
            act_p = s.get("actions_path") or ""
            results.append({
                "sim_id": sid,
                "has_db": bool(db_p) and os.path.exists(db_p),
                "has_actions": bool(act_p) and os.path.exists(act_p),
            })
    except Exception as e:
        logger.warning("list_simulations meta.db query fail: %s", e)
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

        # Auto-save results to the sim directory (paths via meta.db)
        if sim_id:
            _save_analysis_to_dir(sim_id, report)

        return report

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis summary failed: {e}", exc_info=True)
        raise HTTPException(500, detail=f"Analysis failed: {type(e).__name__}: {str(e)}")


def _save_analysis_to_dir(sim_id: str, data: dict):
    """Save analysis results as JSON in the simulation directory.

    Paths resolved from meta.db (`sentiment_path` for the canonical new
    location, `sim_dir` for the legacy mirror). Old signature took `sim_dir`
    directly; callers now pass `sim_id` so this function owns the lookup.
    """
    paths = _sim_paths(sim_id)
    sim_dir = paths.get("sim_dir") or ""
    new_path = paths.get("sentiment_path") or ""
    if not sim_dir or not new_path:
        logger.warning("save_analysis: meta.db missing sim_dir/sentiment_path for %s", sim_id)
        return

    try:
        save_data = {
            "timestamp": datetime.now().isoformat(),
            "results": data,
        }
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
        # Legacy mirror at sim_dir/analysis_results.json — kept for back-compat
        # readers that haven't migrated to the analysis/ subfolder.
        legacy_path = os.path.join(sim_dir, "analysis_results.json")
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info("Analysis results saved to %s (+ legacy mirror)", new_path)
    except Exception as e:
        logger.warning(f"Failed to save analysis results: {e}")
        return

    # Sync sentiment per-round vào metadata DB (best-effort)
    try:
        from ecosim_common.metadata_index import upsert_sentiment_round
        per_round = (
            data.get("per_round")
            or (data.get("results", {}) if isinstance(data.get("results"), dict) else {}).get("per_round")
            or []
        )
        for r in per_round:
            if not isinstance(r, dict):
                continue
            upsert_sentiment_round(
                sim_id, int(r.get("round", 0)),
                int(r.get("positive", 0)),
                int(r.get("negative", 0)),
                int(r.get("neutral", 0)),
            )
    except Exception as _me:
        logger.warning("Metadata sync (sentiment) fail: %s", _me)


@router.post("/save")
async def save_analysis(
    sim_id: str = Query("", description="Simulation ID"),
    data: dict = Body(..., description="Analysis results to save"),
):
    """Save analysis results to the simulation directory."""
    if not sim_id:
        raise HTTPException(400, "sim_id is required")
    _save_analysis_to_dir(sim_id, data)
    return {"status": "saved", "sim_id": sim_id}


@router.get("/cached")
async def get_cached_analysis(
    sim_id: str = Query("", description="Simulation ID"),
):
    """Load previously saved analysis results (paths via meta.db).

    Prefers the new `<sim_dir>/analysis/sentiment.json` location; falls back
    to the legacy `analysis_results.json` mirror for older sims that ran
    before the analysis/ subfolder was introduced.
    """
    paths = _sim_paths(sim_id) if sim_id else {}
    sim_dir = paths.get("sim_dir") or ""
    new_path = paths.get("sentiment_path") or ""
    legacy_path = os.path.join(sim_dir, "analysis_results.json") if sim_dir else ""
    path = new_path if (new_path and os.path.exists(new_path)) else legacy_path

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

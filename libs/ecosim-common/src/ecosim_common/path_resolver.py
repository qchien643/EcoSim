"""
Phase 10: Path resolver — DB-backed file path lookup, nested layout.

NEW LAYOUT (Phase 10):
  data/campaigns/<cid>/                    ← campaign root
    source/<filename>                      ← upload gốc
    extracted/{spec,sections,analyzed}.json ← LLM cache
    kg/build_meta.json                     ← KG provenance only
    sims/<sid>/                            ← NESTED — sim thuộc campaign
      config.json
      profiles.json
      actions.jsonl
      oasis.db
      progress.json
      memory_stats.json
      kg/{zep_buffer.jsonl, zep_buffer_failed.jsonl}
      posts/chroma/                         ← post indexer (KHÔNG liên quan KG)
      analysis/{sentiment.json, tracking.jsonl}
      report/{agent_log.jsonl, *.md}

KG data KHÔNG sống trong filesystem — sống trong FalkorDB graph_name = cid (master)
hoặc graph_name = "sim_<sid>" (sim).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional, TypedDict

from .config import EcoSimConfig

logger = logging.getLogger("ecosim.path_resolver")


# ──────────────────────────────────────────────
# Type defs
# ──────────────────────────────────────────────
class CampaignPaths(TypedDict, total=False):
    cid: str
    campaign_dir: str
    source_dir: str
    extracted_dir: str
    spec_path: str
    sections_path: str
    analyzed_path: str
    kg_dir: str
    build_meta_path: str
    sims_dir: str


class SimulationPaths(TypedDict, total=False):
    sid: str
    cid: str
    sim_dir: str
    config_path: str
    profiles_path: str
    actions_path: str
    oasis_db_path: str
    progress_path: str
    memory_stats_path: str
    kg_dir: str
    zep_buffer_path: str
    posts_chroma_dir: str
    analysis_dir: str
    sentiment_path: str
    tracking_path: str
    tracking_legacy_path: str
    report_dir: str
    report_log_path: str
    crisis_log_path: str
    crisis_pending_path: str
    simulation_log_path: str
    campaign_context_path: str


# ──────────────────────────────────────────────
# Convention path computation
# ──────────────────────────────────────────────
def compute_campaign_paths(cid: str) -> CampaignPaths:
    """All paths cho 1 campaign từ convention. KHÔNG đụng DB."""
    if not cid:
        raise ValueError("cid required")
    cdir = EcoSimConfig.campaigns_dir() / cid
    extracted = cdir / "extracted"
    kg = cdir / "kg"
    sims = cdir / "sims"
    return {
        "cid": cid,
        "campaign_dir": str(cdir),
        "source_dir": str(cdir / "source"),
        "extracted_dir": str(extracted),
        "spec_path": str(extracted / "spec.json"),
        "sections_path": str(extracted / "sections.json"),
        "analyzed_path": str(extracted / "analyzed.json"),
        "kg_dir": str(kg),
        "build_meta_path": str(kg / "build_meta.json"),
        "sims_dir": str(sims),
    }


def compute_simulation_paths(sid: str, cid: str) -> SimulationPaths:
    """All paths cho 1 sim từ convention.

    Phase 10 nested layout: sim_dir = data/campaigns/<cid>/sims/<sid>/
    REQUIRES cid vì path nested dưới campaign.
    """
    if not sid:
        raise ValueError("sid required")
    if not cid:
        raise ValueError("cid required (sim is nested under campaign)")
    sdir = EcoSimConfig.campaigns_dir() / cid / "sims" / sid
    kg = sdir / "kg"
    posts = sdir / "posts"
    analysis = sdir / "analysis"
    report = sdir / "report"
    return {
        "sid": sid,
        "cid": cid,
        "sim_dir": str(sdir),
        "config_path": str(sdir / "config.json"),
        "profiles_path": str(sdir / "profiles.json"),
        "actions_path": str(sdir / "actions.jsonl"),
        # Note: filename is `oasis_simulation.db`, not `oasis.db`. Older
        # versions of this resolver had `oasis.db` but the OASIS subprocess
        # writes `oasis_simulation.db` — backend code at multiple call sites
        # was hardcoding the right name and ignoring this column. Aligned now.
        "oasis_db_path": str(sdir / "oasis_simulation.db"),
        "progress_path": str(sdir / "progress.json"),
        "memory_stats_path": str(sdir / "memory_stats.json"),
        "kg_dir": str(kg),
        "zep_buffer_path": str(kg / "zep_buffer.jsonl"),
        "posts_chroma_dir": str(posts / "chroma"),
        "analysis_dir": str(analysis),
        "sentiment_path": str(analysis / "sentiment.json"),
        "tracking_path": str(analysis / "tracking.jsonl"),
        # Legacy flat-file tracking output (kept for sims produced before the
        # analysis/ folder was introduced; readers should fall back to it).
        "tracking_legacy_path": str(sdir / "agent_tracking.txt"),
        "report_dir": str(report),
        "report_log_path": str(report / "agent_log.jsonl"),
        "crisis_log_path": str(sdir / "crisis_log.json"),
        "crisis_pending_path": str(sdir / "pending_crisis.json"),
        "simulation_log_path": str(sdir / "simulation.log"),
        "campaign_context_path": str(sdir / "campaign_context.txt"),
    }


# ──────────────────────────────────────────────
# DB-backed lookup
# ──────────────────────────────────────────────
def resolve_campaign_paths(cid: str, *, fallback: bool = True) -> CampaignPaths:
    """Get all paths cho 1 campaign từ DB. Fallback convention nếu DB miss."""
    from .metadata_index import get_conn, init_schema, upsert_campaign

    init_schema()
    try:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT campaign_dir, source_dir, extracted_dir, spec_path,
                          sections_path, analyzed_path, kg_dir, build_meta_path, sims_dir
                   FROM campaigns WHERE cid = ?""",
                (cid,),
            ).fetchone()
        if row and row["campaign_dir"]:
            return {
                "cid": cid,
                "campaign_dir": row["campaign_dir"],
                "source_dir": row["source_dir"] or "",
                "extracted_dir": row["extracted_dir"] or "",
                "spec_path": row["spec_path"] or "",
                "sections_path": row["sections_path"] or "",
                "analyzed_path": row["analyzed_path"] or "",
                "kg_dir": row["kg_dir"] or "",
                "build_meta_path": row["build_meta_path"] or "",
                "sims_dir": row["sims_dir"] or "",
            }
    except Exception as e:
        logger.warning("DB path resolve fail cho campaign %s: %s", cid, e)
        if not fallback:
            raise

    if not fallback:
        raise KeyError(f"Campaign {cid} không có paths trong DB")
    paths = compute_campaign_paths(cid)
    try:
        upsert_campaign(cid, status="created")
        _populate_campaign_paths(cid, paths)
    except Exception as e:
        logger.debug("Lazy upsert campaign paths skip: %s", e)
    return paths


def resolve_simulation_paths(sid: str, *, fallback: bool = True) -> SimulationPaths:
    """DB-backed sim path resolver. JOIN campaigns để lấy cid cho fallback."""
    from .metadata_index import get_conn, init_schema

    init_schema()
    try:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT s.cid, s.sim_dir, s.config_path, s.profiles_path, s.actions_path,
                          s.oasis_db_path, s.progress_path, s.memory_stats_path,
                          s.kg_dir, s.zep_buffer_path, s.posts_chroma_dir,
                          s.analysis_dir, s.sentiment_path, s.tracking_path,
                          s.tracking_legacy_path,
                          s.report_dir, s.report_log_path,
                          s.crisis_log_path, s.crisis_pending_path,
                          s.simulation_log_path, s.campaign_context_path
                   FROM simulations s WHERE s.sid = ?""",
                (sid,),
            ).fetchone()
        if row and row["sim_dir"]:
            return {
                "sid": sid,
                "cid": row["cid"],
                "sim_dir": row["sim_dir"],
                "config_path": row["config_path"] or "",
                "profiles_path": row["profiles_path"] or "",
                "actions_path": row["actions_path"] or "",
                "oasis_db_path": row["oasis_db_path"] or "",
                "progress_path": row["progress_path"] or "",
                "memory_stats_path": row["memory_stats_path"] or "",
                "kg_dir": row["kg_dir"] or "",
                "zep_buffer_path": row["zep_buffer_path"] or "",
                "posts_chroma_dir": row["posts_chroma_dir"] or "",
                "analysis_dir": row["analysis_dir"] or "",
                "sentiment_path": row["sentiment_path"] or "",
                "tracking_path": row["tracking_path"] or "",
                "tracking_legacy_path": row["tracking_legacy_path"] or "",
                "report_dir": row["report_dir"] or "",
                "report_log_path": row["report_log_path"] or "",
                "crisis_log_path": row["crisis_log_path"] or "",
                "crisis_pending_path": row["crisis_pending_path"] or "",
                "simulation_log_path": row["simulation_log_path"] or "",
                "campaign_context_path": row["campaign_context_path"] or "",
            }
        # Row exists but paths NULL → need cid để compute fallback
        if row:
            return compute_simulation_paths(sid, row["cid"])
    except Exception as e:
        logger.warning("DB path resolve fail cho sim %s: %s", sid, e)
        if not fallback:
            raise

    if not fallback:
        raise KeyError(f"Simulation {sid} không có paths trong DB")
    raise KeyError(f"Simulation {sid} không tồn tại trong meta.db (cần cid để compute path)")


# ──────────────────────────────────────────────
# Path population helpers
# ──────────────────────────────────────────────
def _populate_campaign_paths(cid: str, paths: Optional[CampaignPaths] = None) -> None:
    from .metadata_index import get_conn

    if paths is None:
        paths = compute_campaign_paths(cid)
    with get_conn() as conn:
        conn.execute(
            """UPDATE campaigns SET
                  campaign_dir = ?, source_dir = ?, extracted_dir = ?,
                  spec_path = ?, sections_path = ?, analyzed_path = ?,
                  kg_dir = ?, build_meta_path = ?, sims_dir = ?
               WHERE cid = ?""",
            (
                paths.get("campaign_dir"), paths.get("source_dir"),
                paths.get("extracted_dir"), paths.get("spec_path"),
                paths.get("sections_path"), paths.get("analyzed_path"),
                paths.get("kg_dir"), paths.get("build_meta_path"),
                paths.get("sims_dir"), cid,
            ),
        )


def _populate_simulation_paths(sid: str, cid: str, paths: Optional[SimulationPaths] = None) -> None:
    from .metadata_index import get_conn

    if paths is None:
        paths = compute_simulation_paths(sid, cid)
    with get_conn() as conn:
        conn.execute(
            """UPDATE simulations SET
                  sim_dir = ?, config_path = ?, profiles_path = ?, actions_path = ?,
                  oasis_db_path = ?, progress_path = ?, memory_stats_path = ?,
                  kg_dir = ?, zep_buffer_path = ?, posts_chroma_dir = ?,
                  analysis_dir = ?, sentiment_path = ?, tracking_path = ?,
                  tracking_legacy_path = ?,
                  report_dir = ?, report_log_path = ?,
                  crisis_log_path = ?, crisis_pending_path = ?,
                  simulation_log_path = ?, campaign_context_path = ?
               WHERE sid = ?""",
            (
                paths.get("sim_dir"), paths.get("config_path"),
                paths.get("profiles_path"), paths.get("actions_path"),
                paths.get("oasis_db_path"), paths.get("progress_path"),
                paths.get("memory_stats_path"), paths.get("kg_dir"),
                paths.get("zep_buffer_path"), paths.get("posts_chroma_dir"),
                paths.get("analysis_dir"), paths.get("sentiment_path"),
                paths.get("tracking_path"),
                paths.get("tracking_legacy_path"),
                paths.get("report_dir"),
                paths.get("report_log_path"),
                paths.get("crisis_log_path"), paths.get("crisis_pending_path"),
                paths.get("simulation_log_path"),
                paths.get("campaign_context_path"),
                sid,
            ),
        )


def populate_campaign_paths(cid: str) -> None:
    """Public — gọi sau upsert_campaign() để DB có paths."""
    _populate_campaign_paths(cid)


def populate_simulation_paths(sid: str, cid: Optional[str] = None) -> None:
    """Public — gọi sau upsert_simulation() để DB có paths.

    Nếu cid không truyền → query từ DB (sim row đã có cid sau upsert).
    """
    if cid is None:
        from .metadata_index import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT cid FROM simulations WHERE sid = ?", (sid,)
            ).fetchone()
        if not row:
            logger.warning("populate_simulation_paths: sim %s not in DB", sid)
            return
        cid = row["cid"]
    _populate_simulation_paths(sid, cid)


# ──────────────────────────────────────────────
# Mkdir helpers — tạo folders thực tế trên disk
# ──────────────────────────────────────────────
def ensure_campaign_dirs(cid: str) -> None:
    """mkdir -p campaign folder structure."""
    paths = compute_campaign_paths(cid)
    for key in ("campaign_dir", "source_dir", "extracted_dir", "kg_dir", "sims_dir"):
        Path(paths[key]).mkdir(parents=True, exist_ok=True)


def ensure_simulation_dirs(sid: str, cid: str) -> None:
    """mkdir -p sim folder structure (nested under campaign)."""
    paths = compute_simulation_paths(sid, cid)
    for key in ("sim_dir", "kg_dir", "posts_chroma_dir", "analysis_dir", "report_dir"):
        Path(paths[key]).mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# Backfill — sau migration hoặc drift
# ──────────────────────────────────────────────
def backfill_all_paths() -> Dict[str, int]:
    """Scan meta.db, populate paths cho mọi row chưa có. Idempotent."""
    from .metadata_index import get_conn

    stats = {"campaigns_filled": 0, "simulations_filled": 0}
    with get_conn() as conn:
        c_rows = conn.execute(
            "SELECT cid FROM campaigns WHERE campaign_dir IS NULL"
        ).fetchall()
        for r in c_rows:
            try:
                _populate_campaign_paths(r["cid"])
                stats["campaigns_filled"] += 1
            except Exception as e:
                logger.warning("Backfill paths cho %s fail: %s", r["cid"], e)

        s_rows = conn.execute(
            "SELECT sid, cid FROM simulations WHERE sim_dir IS NULL"
        ).fetchall()
        for r in s_rows:
            try:
                _populate_simulation_paths(r["sid"], r["cid"])
                stats["simulations_filled"] += 1
            except Exception as e:
                logger.warning("Backfill paths cho %s fail: %s", r["sid"], e)
    logger.info("Backfill paths: %s", stats)
    return stats

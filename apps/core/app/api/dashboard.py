"""
Dashboard API — cross-cutting metadata aggregations từ meta.db.

Phase 7.5: tận dụng SQLite index để serve dashboard queries nhanh thay vì
walk filesystem mỗi request.

Endpoints:
  GET /api/dashboard/summary           — tổng quan campaigns + sims + sentiment trends
  GET /api/dashboard/recent-sims       — sims trong N ngày qua, filter status
  GET /api/dashboard/mbti-distribution — phân bố MBTI across all sims
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, request

from ecosim_common.config import EcoSimConfig
from ecosim_common.metadata_index import (
    list_campaigns, list_simulations, init_schema, get_conn,
)

logger = logging.getLogger("ecosim.api.dashboard")

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@dashboard_bp.route("/summary", methods=["GET"])
def get_summary():
    """Aggregate stats cho dashboard top cards.

    Returns:
        {
          "campaigns": {"total": N, "ready": M, "building": K, "failed": J},
          "simulations": {"total": N, "completed": M, "running": K, "ready": J,
                          "failed": L, "preparing": P},
          "kg": {"total_nodes": sum, "total_edges": sum},
          "sentiment_avg": {"positive": float, "negative": float, "neutral": float}
              # Average across all completed sims with sentiment data
        }
    """
    init_schema()
    try:
        with get_conn() as conn:
            # Campaigns by status
            c_rows = conn.execute(
                "SELECT status, COUNT(*) FROM campaigns GROUP BY status"
            ).fetchall()
            campaigns_by_status = {r["status"]: r[1] for r in c_rows}

            # Sims by status
            s_rows = conn.execute(
                "SELECT status, COUNT(*) FROM simulations GROUP BY status"
            ).fetchall()
            sims_by_status = {r["status"]: r[1] for r in s_rows}

            # KG totals
            kg_row = conn.execute(
                "SELECT SUM(kg_node_count), SUM(kg_edge_count) FROM campaigns"
            ).fetchone()
            kg_nodes = int(kg_row[0] or 0)
            kg_edges = int(kg_row[1] or 0)

            # Sentiment averages (across all rounds across all sims)
            senti_row = conn.execute(
                "SELECT AVG(positive), AVG(negative), AVG(neutral), COUNT(*) "
                "FROM sentiment_summaries"
            ).fetchone()
            senti_avg = {
                "positive": float(senti_row[0] or 0),
                "negative": float(senti_row[1] or 0),
                "neutral": float(senti_row[2] or 0),
                "samples": int(senti_row[3] or 0),
            }

        return jsonify({
            "campaigns": {
                "total": sum(campaigns_by_status.values()),
                **campaigns_by_status,
            },
            "simulations": {
                "total": sum(sims_by_status.values()),
                **sims_by_status,
            },
            "kg": {"total_nodes": kg_nodes, "total_edges": kg_edges},
            "sentiment_avg": senti_avg,
        })
    except Exception as e:
        logger.error("Dashboard summary fail: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route("/recent-sims", methods=["GET"])
def get_recent_sims():
    """Recent sims (default last 7 days). Filter qua query params."""
    init_schema()
    days = int(request.args.get("days", "7"))
    status_filter = request.args.get("status", "").strip()
    limit = min(int(request.args.get("limit", "50")), 200)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")

    try:
        with get_conn() as conn:
            sql = """
                SELECT s.sid, s.cid, s.status, s.num_agents, s.num_rounds,
                       s.current_round, s.created_at, s.completed_at,
                       s.last_accessed_at, c.name AS campaign_name
                FROM simulations s
                LEFT JOIN campaigns c ON c.cid = s.cid
                WHERE s.created_at >= ?
            """
            params = [cutoff]
            if status_filter:
                sql += " AND s.status = ?"
                params.append(status_filter)
            sql += " ORDER BY s.created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            sims = [dict(r) for r in rows]
        return jsonify({"sims": sims, "count": len(sims), "days": days})
    except Exception as e:
        logger.error("Dashboard recent-sims fail: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route("/mbti-distribution", methods=["GET"])
def get_mbti_distribution():
    """MBTI distribution across all simulation_agents.

    Optional query: ?cid=<campaign_id> để filter 1 campaign.
    """
    init_schema()
    cid = request.args.get("cid", "").strip()
    try:
        with get_conn() as conn:
            if cid:
                sql = (
                    "SELECT a.mbti, COUNT(*) FROM simulation_agents a "
                    "JOIN simulations s ON s.sid = a.sid "
                    "WHERE s.cid = ? GROUP BY a.mbti"
                )
                rows = conn.execute(sql, (cid,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT mbti, COUNT(*) FROM simulation_agents GROUP BY mbti"
                ).fetchall()
            dist = {r[0] or "?": int(r[1]) for r in rows}
        return jsonify({"distribution": dist, "campaign_id": cid or None})
    except Exception as e:
        logger.error("Dashboard mbti fail: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route("/sentiment-timeseries", methods=["GET"])
def get_sentiment_timeseries():
    """Sentiment per round, optionally filtered by sim_id hoặc cid."""
    init_schema()
    sid = request.args.get("sid", "").strip()
    cid = request.args.get("cid", "").strip()
    try:
        with get_conn() as conn:
            if sid:
                rows = conn.execute(
                    "SELECT round, positive, negative, neutral FROM sentiment_summaries "
                    "WHERE sid = ? ORDER BY round",
                    (sid,),
                ).fetchall()
            elif cid:
                rows = conn.execute(
                    "SELECT ss.round, AVG(ss.positive), AVG(ss.negative), AVG(ss.neutral) "
                    "FROM sentiment_summaries ss "
                    "JOIN simulations s ON s.sid = ss.sid "
                    "WHERE s.cid = ? GROUP BY ss.round ORDER BY ss.round",
                    (cid,),
                ).fetchall()
            else:
                # Aggregate across all
                rows = conn.execute(
                    "SELECT round, AVG(positive), AVG(negative), AVG(neutral) "
                    "FROM sentiment_summaries GROUP BY round ORDER BY round"
                ).fetchall()
            series = [
                {"round": int(r[0]),
                 "positive": float(r[1] or 0),
                 "negative": float(r[2] or 0),
                 "neutral": float(r[3] or 0)}
                for r in rows
            ]
        return jsonify({"series": series, "sim_id": sid or None, "campaign_id": cid or None})
    except Exception as e:
        logger.error("Dashboard sentiment-timeseries fail: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500

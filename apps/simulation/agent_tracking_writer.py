"""
Phase 6.4: Structured agent tracking → JSONL.

Replace brittle text format ở `agent_tracking.txt` (parsed bằng regex ở
`api/simulation.py:_parse_tracking_file`). Ghi song song JSONL ở
`<sim_dir>/analysis/tracking.jsonl` cho new structured access; legacy text
file vẫn ghi cho backward compat.

Schema mỗi line (1 line / agent / round):
{
  "round": int (0 = initial state),
  "agent_id": int, "agent_name": str, "mbti": str,
  "base_persona": str, "evolved_persona": str,
  "cognitive_traits": {conviction, forgetfulness, curiosity, impressionability},
  "interest_vector": [{keyword, weight, source, engagement_count, trending, is_new}],
  "search_queries": [{weight, query}],
  "mbti_modifiers": {post_mult, comment_mult, like_mult, feed_mult},
  "drift_keywords": [str],
  "memory": str,
  "graph_context": str,
  "actions": [{"type": str, "text": str}],
  "ts": iso8601
}
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _tracking_paths(sim_dir: str) -> tuple:
    """Returns (new_path, legacy_path)."""
    new_path = Path(sim_dir) / "analysis" / "tracking.jsonl"
    legacy_path = Path(sim_dir) / "agent_tracking.txt"
    return new_path, legacy_path


def init_tracking(sim_dir: str) -> None:
    """Truncate JSONL file (Round 0 sẽ là first record)."""
    new_path, _ = _tracking_paths(sim_dir)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_text("", encoding="utf-8")


def write_agent_round(
    sim_dir: str,
    *,
    round_num: int,
    agent_id: int,
    agent_name: str,
    mbti: str,
    base_persona: str = "",
    evolved_persona: str = "",
    cognitive_traits: Optional[Dict[str, Any]] = None,
    interest_vector: Optional[List[Dict[str, Any]]] = None,
    search_queries: Optional[List[Dict[str, Any]]] = None,
    mbti_modifiers: Optional[Dict[str, Any]] = None,
    drift_keywords: Optional[List[str]] = None,
    memory: str = "",
    graph_context: str = "",
    actions: Optional[List[Dict[str, str]]] = None,
) -> None:
    """Append 1 record cho 1 agent ở 1 round vào tracking.jsonl. Best-effort."""
    new_path, _ = _tracking_paths(sim_dir)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "round": int(round_num),
        "agent_id": int(agent_id),
        "agent_name": str(agent_name),
        "mbti": str(mbti or ""),
        "base_persona": str(base_persona or ""),
        "evolved_persona": str(evolved_persona or base_persona or ""),
        "cognitive_traits": cognitive_traits or {},
        "interest_vector": interest_vector or [],
        "search_queries": search_queries or [],
        "mbti_modifiers": mbti_modifiers or {},
        "drift_keywords": drift_keywords or [],
        "memory": str(memory or ""),
        "graph_context": str(graph_context or ""),
        "actions": actions or [],
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        with open(new_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # silent fail; legacy text writer vẫn capture data


def parse_tracking_jsonl(jsonl_path: str) -> Dict[str, Any]:
    """Parse JSONL tracking file → multi-agent grouped output.

    Phase 15.tracking: tracking.jsonl ghi N+1 record/agent × M agents. Group
    records theo agent_id để frontend chọn agent xem timeline.

    Output structure:
      {
        "agents": [
          {
            "agent": {"name", "id", "mbti"},
            "rounds": [...],         # round records (Round 0..N)
            "total_rounds": int,
          },
          ...
        ],
        # Backward compat fields (= agents[0]) cho clients cũ:
        "agent": {...},
        "rounds": [...],
        "total_rounds": int,
      }
    """
    empty_response = {
        "agents": [], "agent": {}, "rounds": [], "total_rounds": 0,
    }
    if not os.path.exists(jsonl_path):
        return empty_response

    records: List[Dict[str, Any]] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue

    if not records:
        return empty_response

    # Group records theo agent_id (preserve order of first occurrence)
    by_agent: Dict[int, List[Dict[str, Any]]] = {}
    order: List[int] = []
    for r in records:
        try:
            aid = int(r.get("agent_id", 0))
        except (TypeError, ValueError):
            continue
        if aid not in by_agent:
            by_agent[aid] = []
            order.append(aid)
        by_agent[aid].append(r)

    label_map = {
        "conviction": "Độ bảo thủ",
        "forgetfulness": "Độ hay quên",
        "curiosity": "Độ tò mò",
        "impressionability": "Độ dễ bị ảnh hưởng",
    }

    agents_out: List[Dict[str, Any]] = []
    for aid in order:
        recs = by_agent[aid]
        first = recs[0]
        agent_info = {
            "name": first.get("agent_name", ""),
            "id": first.get("agent_id", 0),
            "mbti": first.get("mbti", ""),
        }

        rounds_out = []
        for r in recs:
            ct_raw = r.get("cognitive_traits") or {}
            ct_render = {}
            for key, label in label_map.items():
                if key in ct_raw:
                    ct_render[key] = {
                        "value": float(ct_raw[key]),
                        "label": label,
                        "description": "",
                    }

            iv = r.get("interest_vector") or []
            interest_query = ", ".join(
                f"{i.get('keyword','')}({i.get('weight',0):.2f})" for i in iv[:5]
            )

            rounds_out.append({
                "round": r.get("round", 0),
                "base_persona": r.get("base_persona", ""),
                "evolved_persona": r.get("evolved_persona", "") or r.get("base_persona", ""),
                "insights_count": 0,
                "reflections": "",
                "memory": r.get("memory", ""),
                "cognitive_traits": ct_render,
                "interest_vector": iv,
                "search_queries": r.get("search_queries") or [],
                "drift_keywords": r.get("drift_keywords") or [],
                "initial_interests": [],
                "interest_query": interest_query,
                "search_query": "",
                "mbti_modifiers": _render_mbti_mods_text(r.get("mbti_modifiers") or {}),
                "graph_context": r.get("graph_context", ""),
                "actions": r.get("actions") or [],
            })
        # sort rounds ascending
        rounds_out.sort(key=lambda x: x["round"])
        agents_out.append({
            "agent": agent_info,
            "rounds": rounds_out,
            "total_rounds": len(rounds_out),
        })

    # Backward-compat top-level fields = first agent
    first_agent = agents_out[0] if agents_out else {"agent": {}, "rounds": [], "total_rounds": 0}
    return {
        "agents": agents_out,
        "agent": first_agent.get("agent", {}),
        "rounds": first_agent.get("rounds", []),
        "total_rounds": first_agent.get("total_rounds", 0),
    }


def _render_mbti_mods_text(mods: Dict[str, Any]) -> str:
    """Render mbti_modifiers dict → string khớp legacy text format."""
    if not mods:
        return ""
    return (
        f"post_mult={mods.get('post_mult', 1.0)}, "
        f"comment_mult={mods.get('comment_mult', 1.0)}, "
        f"like_mult={mods.get('like_mult', 1.0)}, "
        f"feed_mult={mods.get('feed_mult', 1.0)}"
    )

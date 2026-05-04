"""
Sim master mutator — agents modify cloned master entities qua reflection.

Phase 4 implementation: agents nói gì về master entity (vd "Shopee giảm phí ship")
qua reflection cycle → LLM extract mutations → áp lên sim_<sid> graph + persist
vào master_mutations.jsonl cho cascade restore.

Schema mutation:
  {round, agent_id, ts, action, entity, attr_key?, attr_value?, edge_uuid?}

Trong đó action ∈:
  - "update_attr"      : SET (n {name: $entity}).{attr_key} = $attr_value
  - "invalidate_edge"  : SET r.expired_at = $ts trên edge có $edge_uuid

Master entities chỉ MUTATE trong sim graph `sim_<sid>` — KHÔNG touch master `<cid>`
graph (separate FalkorDB graphs đã isolate). Cascade restore replay mutations
sau fork để đạt state cuối sim.

Validation: entity_name PHẢI exact-match name của entity trong master snapshot
để tránh LLM hallucinate. Edge_uuid lookup từ sim graph hiện tại.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("sim-svc.sim_master_mutator")

MUTATION_PROMPT = """\
Bạn phân tích reflection insights của 1 agent trong simulation. Trích xuất
các thay đổi (mutation) mà agent's reflection ngụ ý cho master entities.

Master entities (chỉ được mutate những entity tên trong list này):
{entity_list}

Reflection insights (round {round_num}, agent {agent_id}):
{insights_block}

Trả STRICT JSON:
{{
  "mutations": [
    {{"action": "update_attr", "entity": "<exact_name>", "attr_key": "<short_snake_case>", "attr_value": "<scalar_value>"}},
    {{"action": "invalidate_edge", "entity": "<exact_name>", "edge_predicate": "<COMPETES_WITH|HOSTS|SUPPORTS|...>", "target_entity": "<exact_name>"}}
  ]
}}

Quy tắc:
- entity / target_entity PHẢI exact match trong list trên (no fuzzy, no synonym).
- attr_key snake_case, ngắn (vd "recent_promo", "shipping_fee_change").
- attr_value scalar string ngắn (≤100 chars) — không object/array.
- KHÔNG fabricate. Nếu insights không nói rõ thay đổi nào → return `{{"mutations": []}}`.
- 0-3 mutations per call. Skip ngụ ý mơ hồ.
"""


def _mutations_log_path(sim_dir: Path) -> Path:
    return Path(sim_dir) / "kg" / "master_mutations.jsonl"


async def analyze_reflection_for_mutations(
    insights: List[str],
    master_entity_names: Set[str],
    *,
    round_num: int,
    agent_id: int,
    llm_client: Any,
) -> List[Dict[str, Any]]:
    """LLM extract mutations từ reflection insights. Returns validated list.

    Returns empty list nếu LLM fail hoặc insights không có mutation rõ ràng.
    """
    if not insights or not master_entity_names:
        return []

    insights_block = "\n".join(f"- {s}" for s in insights if s and s.strip())
    if not insights_block.strip():
        return []

    entity_list = "\n".join(f"  - {name}" for name in sorted(master_entity_names))
    prompt = MUTATION_PROMPT.format(
        entity_list=entity_list,
        round_num=round_num,
        agent_id=agent_id,
        insights_block=insights_block,
    )

    try:
        raw = await llm_client.chat_json_async(
            messages=[
                {"role": "system", "content": "Bạn là extractor chính xác. Output STRICT JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=600,
        )
    except Exception as e:
        logger.warning("LLM mutation extract fail (agent=%s, round=%s): %s",
                       agent_id, round_num, e)
        return []

    raw_muts = raw.get("mutations", []) if isinstance(raw, dict) else []
    validated: List[Dict[str, Any]] = []
    for m in raw_muts:
        if not isinstance(m, dict):
            continue
        action = m.get("action")
        entity = (m.get("entity") or "").strip()
        if entity not in master_entity_names:
            logger.debug("Drop mutation: entity '%s' not in master", entity)
            continue
        if action == "update_attr":
            attr_key = (m.get("attr_key") or "").strip()
            attr_value = m.get("attr_value")
            if not attr_key or attr_value is None:
                continue
            # Whitelist attr_key — chỉ snake_case, alphanumeric
            if not all(c.isalnum() or c == "_" for c in attr_key):
                continue
            validated.append({
                "action": "update_attr",
                "entity": entity,
                "attr_key": attr_key[:50],
                "attr_value": str(attr_value)[:100],
            })
        elif action == "invalidate_edge":
            target = (m.get("target_entity") or "").strip()
            predicate = (m.get("edge_predicate") or "").strip().upper()
            if target not in master_entity_names or not predicate:
                continue
            validated.append({
                "action": "invalidate_edge",
                "entity": entity,
                "target_entity": target,
                "edge_predicate": predicate,
            })

    return validated[:3]  # Cap 3 mutations/call


def apply_mutations(
    sim_id: str,
    sim_dir: str,
    mutations: List[Dict[str, Any]],
    *,
    round_num: int,
    agent_id: int,
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
) -> int:
    """Apply mutations vào FalkorDB sim_<sid> graph + persist log.

    Returns count of mutations applied successfully.
    """
    if not mutations:
        return 0

    from falkordb import FalkorDB
    fdb = FalkorDB(host=falkor_host, port=int(falkor_port))
    sim_graph = sim_id if sim_id.startswith("sim_") else f"sim_{sim_id}"
    g = fdb.select_graph(sim_graph)

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    applied = 0
    log_entries: List[Dict[str, Any]] = []

    for m in mutations:
        try:
            if m["action"] == "update_attr":
                # SET attr trên Entity match name. Tag với updated_by_agent + round.
                cypher = (
                    "MATCH (n:Entity {name: $name}) "
                    f"SET n.{m['attr_key']} = $val, "
                    "    n.updated_by_agent = $aid, "
                    "    n.updated_at_round = $round, "
                    "    n.updated_at_ts = $ts "
                    "RETURN count(n) AS hit"
                )
                r = g.query(cypher, {
                    "name": m["entity"], "val": m["attr_value"],
                    "aid": agent_id, "round": round_num, "ts": ts,
                })
                hit = r.result_set[0][0] if r.result_set else 0
                if hit > 0:
                    applied += 1
                    log_entries.append({
                        "round": round_num, "agent_id": agent_id, "ts": ts,
                        "action": "update_attr", "entity": m["entity"],
                        "attr_key": m["attr_key"], "attr_value": m["attr_value"],
                    })
            elif m["action"] == "invalidate_edge":
                # SET expired_at trên edge match (entity)-[predicate]->(target).
                cypher = (
                    f"MATCH (a:Entity {{name: $src}})-[r:{m['edge_predicate']}]->(b:Entity {{name: $dst}}) "
                    "SET r.expired_at = $ts, "
                    "    r.invalidated_by_agent = $aid, "
                    "    r.invalidated_at_round = $round "
                    "RETURN count(r) AS hit"
                )
                r = g.query(cypher, {
                    "src": m["entity"], "dst": m["target_entity"],
                    "aid": agent_id, "round": round_num, "ts": ts,
                })
                hit = r.result_set[0][0] if r.result_set else 0
                if hit > 0:
                    applied += 1
                    log_entries.append({
                        "round": round_num, "agent_id": agent_id, "ts": ts,
                        "action": "invalidate_edge", "entity": m["entity"],
                        "target_entity": m["target_entity"],
                        "edge_predicate": m["edge_predicate"],
                    })
        except Exception as e:
            logger.warning("apply_mutation fail %s: %s", m, e)

    # Persist log (append-only)
    if log_entries:
        log_path = _mutations_log_path(Path(sim_dir))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            for entry in log_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(
            "Master mutations applied: %d (sim=%s, agent=%s, round=%s)",
            applied, sim_id, agent_id, round_num,
        )

    return applied


def replay_mutations(
    sim_id: str,
    sim_dir: str,
    *,
    falkor_host: str = "localhost",
    falkor_port: int = 6379,
) -> int:
    """Replay tất cả mutations từ log lên sim graph (cho cascade_restore_sim).

    Idempotent qua MERGE pattern + SET (overwrite an toàn).
    Returns count replayed.
    """
    log_path = _mutations_log_path(Path(sim_dir))
    if not log_path.exists():
        return 0

    entries: List[Dict[str, Any]] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue

    # Group by (round, agent) để gọi apply_mutations theo batch
    from collections import defaultdict
    grouped: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for e in entries:
        key = (e.get("round", 0), e.get("agent_id", 0))
        grouped[key].append(e)

    total = 0
    for (round_num, agent_id), muts in grouped.items():
        # Re-apply (idempotent SET). Skip log re-write (tránh duplicate).
        from falkordb import FalkorDB
        fdb = FalkorDB(host=falkor_host, port=int(falkor_port))
        sim_graph = sim_id if sim_id.startswith("sim_") else f"sim_{sim_id}"
        g = fdb.select_graph(sim_graph)
        for m in muts:
            try:
                ts = m.get("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
                if m["action"] == "update_attr":
                    cypher = (
                        "MATCH (n:Entity {name: $name}) "
                        f"SET n.{m['attr_key']} = $val, "
                        "    n.updated_by_agent = $aid, "
                        "    n.updated_at_round = $round, "
                        "    n.updated_at_ts = $ts"
                    )
                    g.query(cypher, {
                        "name": m["entity"], "val": m["attr_value"],
                        "aid": agent_id, "round": round_num, "ts": ts,
                    })
                    total += 1
                elif m["action"] == "invalidate_edge":
                    cypher = (
                        f"MATCH (a:Entity {{name: $src}})-[r:{m['edge_predicate']}]->(b:Entity {{name: $dst}}) "
                        "SET r.expired_at = $ts, "
                        "    r.invalidated_by_agent = $aid, "
                        "    r.invalidated_at_round = $round"
                    )
                    g.query(cypher, {
                        "src": m["entity"], "dst": m["target_entity"],
                        "aid": agent_id, "round": round_num, "ts": ts,
                    })
                    total += 1
            except Exception as e:
                logger.warning("replay_mutation fail %s: %s", m, e)

    if total:
        logger.info("Replayed %d master mutations cho sim %s", total, sim_id)
    return total

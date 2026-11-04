"""Exploratory Persona–Behavior Alignment benchmark.

This is a method-evaluation proxy, not a real-world accuracy metric. It asks
whether an ordered persona attribute is reflected in a related behavior.

Default benchmark:
    cog_attention_span -> A1 normalized attention score

The default uses session 1 because it is the least contaminated by repeated
exposure and accumulated history. Later sessions can be selected explicitly.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_ORDER = ("Very short", "Short", "Average", "Long", "Very long")
DEFAULT_DB = (
    Path(__file__).resolve().parents[1]
    / "experiments/cafe-live-100x3-20260928.sqlite"
)


def _rank(values: list[float]) -> list[float]:
    """Average ranks for ties, without requiring scipy."""
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average = (index + 1 + end) / 2
        for position in range(index, end):
            ranks[ordered[position][0]] = average
        index = end
    return ranks


def _spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 2:
        return None
    rx, ry = _rank(x), _rank(y)
    mean_x, mean_y = sum(rx) / len(rx), sum(ry) / len(ry)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    denominator_x = sum((a - mean_x) ** 2 for a in rx)
    denominator_y = sum((b - mean_y) ** 2 for b in ry)
    denominator = math.sqrt(denominator_x * denominator_y)
    return None if denominator == 0 else numerator / denominator


def _pairwise_order_score(means: list[float]) -> float | None:
    """Fraction of ordered group pairs that follow the expected direction."""
    comparisons = 0
    passed = 0.0
    for lower in range(len(means)):
        for higher in range(lower + 1, len(means)):
            comparisons += 1
            if means[higher] > means[lower]:
                passed += 1.0
            elif means[higher] == means[lower]:
                passed += 0.5
    return None if comparisons == 0 else passed / comparisons


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _load_rows(
    db_path: Path,
    run_id: str | None,
    session_no: int | None,
    attribute: str,
    order: tuple[str, ...],
) -> tuple[str, list[dict[str, Any]]]:
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if run_id is None:
            run = connection.execute(
                "SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if run is None:
                raise ValueError("Database contains no runs")
            run_id = run["run_id"]

        query = """
            SELECT e.agent_id, e.session_id, s.session_no, e.object_id,
                   e.action, e.normalized_score, a.persona_json
            FROM stage_events e
            JOIN sessions s ON s.session_id = e.session_id
            JOIN agents a ON a.agent_id = e.agent_id
            WHERE e.run_id = ? AND e.stage = 'A1'
              AND e.status = 'resolved'
        """
        parameters: list[Any] = [run_id]
        if session_no is not None:
            query += " AND s.session_no = ?"
            parameters.append(session_no)
        query += " ORDER BY s.session_no, e.agent_id, e.sequence_no"
        rows = []
        for row in connection.execute(query, parameters):
            persona = json.loads(row["persona_json"])
            value = persona.get(attribute)
            if value not in order:
                continue
            rows.append({
                "agent_id": row["agent_id"],
                "session_no": row["session_no"],
                "object_id": row["object_id"],
                "action": row["action"],
                "score": float(row["normalized_score"]),
                "attribute_value": value,
            })
        return run_id, rows
    finally:
        connection.close()


def benchmark(
    db_path: Path,
    *,
    run_id: str | None = None,
    session_no: int | None = 1,
    attribute: str = "cog_attention_span",
    order: tuple[str, ...] = DEFAULT_ORDER,
) -> dict[str, Any]:
    run_id, rows = _load_rows(db_path, run_id, session_no, attribute, order)
    if not rows:
        raise ValueError(
            f"No resolved A1 rows for attribute={attribute!r}, "
            f"session_no={session_no!r}"
        )

    agent_scores: dict[str, list[float]] = defaultdict(list)
    agent_actions: dict[str, list[str]] = defaultdict(list)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        agent_scores[row["agent_id"]].append(row["score"])
        agent_actions[row["agent_id"]].append(row["action"])

    # Group statistics use the agent mean, so two scheduled posts do not count
    # as two independent users.
    agent_values: dict[str, str] = {}
    for row in rows:
        agent_values[row["agent_id"]] = row["attribute_value"]
    for agent_id, value in agent_values.items():
        groups[value].append({
            "score": _mean(agent_scores[agent_id]),
            "attend_rate": sum(
                action in {"attend", "attend_again"}
                for action in agent_actions[agent_id]
            ) / len(agent_actions[agent_id]),
        })

    group_report = []
    ordered_means = []
    ordered_attend_rates = []
    for value in order:
        members = groups.get(value, [])
        scores = [item["score"] for item in members]
        attend_rates = [item["attend_rate"] for item in members]
        mean_score = _mean(scores)
        mean_attend = _mean(attend_rates)
        if mean_score is not None:
            ordered_means.append(mean_score)
            ordered_attend_rates.append(mean_attend)
        group_report.append({
            "value": value,
            "agents": len(members),
            "mean_attention_score": mean_score,
            "attention_score_min": min(scores) if scores else None,
            "attention_score_max": max(scores) if scores else None,
            "attend_rate": mean_attend,
        })

    rank_by_agent = [order.index(agent_values[agent_id]) for agent_id in agent_scores]
    score_by_agent = [_mean(agent_scores[agent_id]) for agent_id in agent_scores]
    rho = _spearman(rank_by_agent, score_by_agent)
    pairwise_score = _pairwise_order_score(ordered_means)
    direction_score = max(0.0, rho) if rho is not None else None
    alignment_score = (
        100 * (0.5 * direction_score + 0.5 * pairwise_score)
        if direction_score is not None and pairwise_score is not None
        else None
    )

    return {
        "benchmark": "persona_behavior_alignment_v0",
        "meaning": (
            "Exploratory evidence that the ordered persona attribute is "
            "reflected in A1 attention behavior; not real-world accuracy."
        ),
        "run_id": run_id,
        "session_no": session_no,
        "stage": "A1",
        "attribute": attribute,
        "expected_order": list(order),
        "agents_included": len(agent_scores),
        "resolved_exposures_included": len(rows),
        "metrics": {
            "spearman_rho_agent_level": rho,
            "directional_alignment": direction_score,
            "pairwise_group_order_score": pairwise_score,
            "alignment_score_0_to_100": alignment_score,
        },
        "groups": group_report,
        "limitations": [
            "This is one run without a human behavioral reference.",
            "Persona fields are observationally confounded; this is not a causal effect.",
            "A score near 100 means ordered expression in this run, not realism.",
        ],
    }


def self_check() -> None:
    assert abs(_spearman([0, 1, 2], [0, 1, 2]) - 1.0) < 1e-9
    assert abs(_spearman([0, 1, 2], [2, 1, 0]) + 1.0) < 1e-9
    assert _pairwise_order_score([0.1, 0.2, 0.3]) == 1.0
    assert _pairwise_order_score([0.3, 0.2, 0.1]) == 0.0
    print("PASS: persona-behavior alignment ranking checks")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--session-no", type=int, default=1)
    parser.add_argument("--attribute", default="cog_attention_span")
    parser.add_argument(
        "--order",
        nargs="+",
        default=list(DEFAULT_ORDER),
        help="Ordered enum values from lowest to highest expected attention.",
    )
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    result = benchmark(
        args.db,
        run_id=args.run_id,
        session_no=args.session_no,
        attribute=args.attribute,
        order=tuple(args.order),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

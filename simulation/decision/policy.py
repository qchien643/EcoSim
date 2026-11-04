"""Pure policy resolution for the v1 simulation runtime."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "data/contracts/simulation-policy.v1.json").read_text())
TAG_REGISTRY = json.loads((ROOT / "data/tags/agent_flow_tags.v2.json").read_text())
TAGS = {item["id"]: item for item in TAG_REGISTRY["tags"]}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def normalized_score(probabilities: list[float]) -> float:
    """Convert JEV/LLM's ordered 0..3 distribution to [0, 1]."""
    _require(isinstance(probabilities, list) and len(probabilities) == 4,
             "Expected four ordered-level probabilities")
    _require(
        all(type(value) in (int, float) and math.isfinite(value)
            and 0 <= value <= 1 for value in probabilities),
        "Invalid probability",
    )
    _require(
        abs(sum(probabilities) - 1) <= POLICY["probability_sum_tolerance"],
        "Probabilities must sum to one",
    )
    return sum(level * value for level, value in enumerate(probabilities)) / 3


def attention_action(stage: str, score: float, has_attended: bool, policy=None) -> str:
    POLICY = policy or globals()["POLICY"]
    _require(stage in {"A1", "B1"}, "Not an attention stage")
    _require(type(score) in (int, float) and math.isfinite(score)
             and 0 <= score <= 1, "Invalid attention score")
    return (
        "attend_again" if score >= POLICY["attention_threshold"] and has_attended
        else "attend" if score >= POLICY["attention_threshold"]
        else "skip"
    )


def select_tags(stage: str, distributions: dict[str, list[float]], bundle=None) -> dict[str, Any]:
    POLICY = bundle["policy"] if bundle else globals()["POLICY"]
    TAGS = {t["id"]: t for t in bundle["tag_registry"]["tags"]} if bundle else globals()["TAGS"]
    config = POLICY["tag_selection"].get(stage)
    _require(config is not None, "Not a tag-selection stage")
    expected = {
        tag_id for tag_id, tag in TAGS.items() if tag["family"] == config["family"]
    }
    _require(isinstance(distributions, dict) and set(distributions) == expected,
             "Tag response must score the complete permitted family")
    scores = [
        {
            "tag_id": tag_id,
            "score": normalized_score(distributions[tag_id]),
            "description": TAGS[tag_id]["description"],
        }
        for tag_id in expected
    ]
    scores.sort(key=lambda item: (-item["score"], item["tag_id"]))
    selected = [
        item for item in scores if item["score"] >= config["score_floor"]
    ][: config["top_k"]]
    return {"scores": scores, "selected_tags": selected}


def allowed_choices(stage: str, history: dict[str, Any]) -> set[str]:
    if stage == "A4":
        return (
            {"like", "dislike", "no_reaction"}
            if history.get("current_reaction") is None
            else {"keep_current", "remove_reaction", "no_new_reaction"}
        )
    if stage == "A5":
        return (
            {"visit", "not_visit"}
            if history.get("shop_visit_count", 0) == 0
            else {"visit_again", "not_visit_again"}
        )
    if stage == "B3":
        return (
            {"buy", "not_buy"}
            if history.get("purchase_count", 0) == 0
            else {"buy_again", "not_buy_again"}
        )
    raise ValueError(f"Unsupported choice stage: {stage}")


def resolve(stage: str, response: dict[str, Any], *,
            history: dict[str, Any], has_attended: bool, bundle=None) -> dict[str, Any]:
    """Validate one adapter response and produce a normalized result."""
    if not isinstance(response, dict):
        return {"status": "invalid", "source": None, "reason": "not_an_object"}
    if response.get("status") == "invalid":
        return {"status": "invalid", "source": response.get("source"),
                "reason": response.get("reason", "adapter_invalid")}

    source = response.get("source")
    if stage in {"A1", "B1"}:
        try:
            score = normalized_score(response["probabilities"])
            action = attention_action(stage, score, has_attended,
                                      bundle["policy"] if bundle else None)
        except (KeyError, TypeError, ValueError) as error:
            return {"status": "invalid", "source": source, "reason": str(error)}
        return {
            "status": "resolved",
            "source": source,
            "normalized_score": score,
            "action": action,
            "scores": [],
        }

    if stage in {"A2", "A3", "A1R", "B1R", "B2"}:
        try:
            selection = select_tags(stage, response["distributions"], bundle)
        except (KeyError, TypeError, ValueError) as error:
            return {"status": "invalid", "source": source, "reason": str(error)}
        status = "resolved" if selection["selected_tags"] else "below_floor"
        return {
            "status": status,
            "source": source,
            "normalized_score": None,
            "action": None,
            "scores": selection["scores"],
            "selected_tags": selection["selected_tags"],
        }

    if stage in {"A4", "A5", "B3"}:
        answer = response.get("answer")
        try:
            _require(isinstance(answer, str) and answer in allowed_choices(stage, history),
                     "Choice is not valid for the current history")
        except ValueError as error:
            return {"status": "invalid", "source": source, "reason": str(error)}
        return {
            "status": "resolved",
            "source": source,
            "normalized_score": None,
            "action": answer,
            "scores": [],
        }

    return {"status": "invalid", "source": source, "reason": "unknown_stage"}


def final_status(primary: str, fallback: str | None) -> str:
    """Map attempt outcomes to the persisted terminal stage status."""
    if primary == "resolved":
        return "resolved"
    if fallback == "resolved":
        return "resolved"
    if primary == fallback == "below_floor":
        return "empty_result"
    return "unresolved"

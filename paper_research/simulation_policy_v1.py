"""Offline policy functions; no model calls, database or session engine."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "data/contracts/simulation-policy.v1.json").read_text())
REGISTRY = json.loads((ROOT / "data/tags/agent_flow_tags.v2.json").read_text())
TAGS = {tag["id"]: tag for tag in REGISTRY["tags"]}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def normalized_score(probabilities):
    require(isinstance(probabilities, list) and len(probabilities) == 4,
            "Expected four ordered-level probabilities")
    require(all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1
                for p in probabilities), "Invalid probability")
    require(abs(sum(probabilities) - 1) <= POLICY["probability_sum_tolerance"],
            "Probabilities must sum to one")
    return sum(level * p for level, p in enumerate(probabilities)) / 3


def attention_action(stage, score, has_attended):
    require(stage in {"A1", "B1"}, "Not an attention stage")
    require(type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1,
            "Invalid attention score")
    require(type(has_attended) is bool, "Expected attendance flag")
    if score < POLICY["attention_threshold"]:
        return "skip"
    return "attend_again" if has_attended else "attend"


def select_tags(stage, distributions):
    require(stage in POLICY["tag_selection"], "Not a tag stage")
    config = POLICY["tag_selection"][stage]
    expected = {key for key, tag in TAGS.items() if tag["family"] == config["family"]}
    require(isinstance(distributions, dict) and set(distributions) == expected,
            "Missing or unknown tag; v1 scores the entire stage family")
    scored = [
        {"tag_id": key, "score": normalized_score(value),
         "description": TAGS[key]["description"]}
        for key, value in distributions.items()
    ]
    scored.sort(key=lambda item: (-item["score"], item["tag_id"]))
    return {
        "scores": scored,
        "selected_tags": [item for item in scored
                          if item["score"] >= config["score_floor"]][:config["top_k"]],
    }


def resolve_attempts(jev, fallback=None):
    """Inputs are validated attempt outcomes, not raw model output."""
    allowed = {"usable", "below_floor", "invalid"}
    require(jev in allowed and (fallback is None or fallback in allowed), "Invalid outcome")
    if jev == "usable":
        require(fallback is None, "Do not call fallback after usable JEV output")
        return {"status": "resolved", "source": "jev"}
    if fallback is None:
        return {"status": "pending_fallback", "source": None}
    if fallback == "usable":
        return {"status": "resolved", "source": "llm_fallback"}
    status = "empty_result" if jev == fallback == "below_floor" else "unresolved"
    return {"status": status, "source": None}


def self_check():
    assert normalized_score([0, 0, 1, 0]) == 2 / 3
    assert attention_action("A1", 0.60, False) == "attend"
    assert attention_action("B1", 0.60, True) == "attend_again"
    assert attention_action("A1", 0.599999, True) == "skip"
    for stage, config in POLICY["tag_selection"].items():
        inputs = {key: [1, 0, 0, 0] for key, tag in TAGS.items()
                  if tag["family"] == config["family"]}
        assert select_tags(stage, inputs)["selected_tags"] == []
        for key in inputs:
            inputs[key] = [0, 0, 0, 1]
        result = select_tags(stage, inputs)
        assert len(result["selected_tags"]) == 3
        assert [item["tag_id"] for item in result["selected_tags"]] == sorted(inputs)[:3]
    for jev in ("usable", "below_floor", "invalid"):
        if jev == "usable":
            assert resolve_attempts(jev)["source"] == "jev"
            continue
        assert resolve_attempts(jev)["status"] == "pending_fallback"
        for fallback in ("usable", "below_floor", "invalid"):
            result = resolve_attempts(jev, fallback)
            expected = ("resolved" if fallback == "usable" else
                        "empty_result" if jev == fallback == "below_floor" else "unresolved")
            assert result["status"] == expected
    for bad in ([True, 0, 0, 0], [float("nan"), 0, 0, 1], [0, 0, 0, 0], [1.1, 0, 0, -0.1]):
        try:
            normalized_score(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid distribution accepted")
    print("PASS: v1 normalization, attention boundary, 5 tag stages, fallback truth table")


if __name__ == "__main__":
    self_check()

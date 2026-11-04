"""Offline checks for the new vocabulary; never imports the legacy mapping."""
import copy
import json
import math
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data/tags/agent_flow_tags.v2.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_registry(data):
    require(data["version"] == "2.0-draft", "unexpected vocabulary version")
    require(data["language"] == "en", "descriptions must be English")
    families = data["families"]
    require(set(families) == {"enterprise", "article", "product", "thought", "emotion",
                               "attention_reason"},
            "unexpected families")
    stages = {"A1", "A1R", "A2", "A3", "A4", "A5", "B1", "B1R", "B2", "B3"}
    for family in families.values():
        require(bool(family["stages"]) and set(family["stages"]) <= stages, "unknown stage")
        require(family["scale"] is None or family["scale"] in data["scales"], "unknown scale")
    require(families["emotion"]["stages"] == ["A2", "A3"], "emotion stage drift")
    require(families["thought"]["stages"] == ["B2"], "thought stage drift")
    require(families["attention_reason"]["stages"] == ["A1R", "B1R"],
            "attention reason stage drift")
    for scale in data["scales"].values():
        require(len(scale["criteria"]) == 4, "draft scale requires four levels")
        require(len(set(scale["criteria"])) == 4, "duplicate level")
        require(all(isinstance(s, str) and s.strip() for s in scale["criteria"]), "empty level")
        require("{description}" in scale["instructions_template"]
                and "{boundary}" in scale["instructions_template"], "missing tag semantics")
    by_id = {}
    for tag in data["tags"]:
        require(set(tag) == {"id", "family", "group", "description", "boundary", "example", "non_example"},
                "unexpected tag fields")
        require(all(isinstance(v, str) and v.strip() for v in tag.values()), "empty tag field")
        require(tag["family"] in families, "unknown family")
        require(re.fullmatch(tag["family"] + r"\.[a-z][a-z_]*", tag["id"]), "invalid ID")
        require(tag["id"] not in by_id, "duplicate ID")
        by_id[tag["id"]] = tag
    require({t["family"] for t in by_id.values()} == set(families), "empty family")
    for pair in data["cooccurrence"]["review_pairs"]:
        require(len(pair) == 2 and pair[0] != pair[1] and set(pair) <= set(by_id), "bad review pair")
    selection = data["selection_policy"]
    require(selection["normalization_method"] == "expected_level_divided_by_highest_level",
            "unexpected normalization policy")
    require(selection["top_k"] == 3 and selection["score_floor"] == 0.3,
            "unexpected default tag policy")
    require(selection["tie_break"] == "tag_id_ascending", "unexpected tie break")
    expected_overrides = {
        "A1R": {"top_k": 3, "score_floor": 0.5},
        "B1R": {"top_k": 3, "score_floor": 0.5},
        "A2": {"top_k": 3, "score_floor": 0.3},
        "A3": {"top_k": 3, "score_floor": 0.3},
        "B2": {"top_k": 3, "score_floor": 0.3},
    }
    require(selection["stage_overrides"] == expected_overrides,
            "unexpected stage tag policy")
    policy = json.loads((PATH.parent / selection["policy_ref"]).read_text())
    require(policy["normalization"] == selection["normalization_method"], "policy drift")
    require(policy["tie_break"] == selection["tie_break"], "tie-break policy drift")
    require({stage: {k: v for k, v in config.items() if k != "family"}
             for stage, config in policy["tag_selection"].items()} == expected_overrides,
            "stage policy drift")
    return by_id


def validate_selected(data, stage, object_type, tags):
    """Validate normalized tag records, not raw JEV/LLM responses or full events."""
    by_id = {t["id"]: t for t in data["tags"]}
    require((stage, object_type) in {
                ("A1R", "article"), ("B1R", "product"),
                ("A2", "article"), ("A3", "article"), ("B2", "product")
            },
            "stage does not emit this state")
    require(isinstance(tags, list), "tags must be a list")
    seen = set()
    for item in tags:
        require(isinstance(item, dict) and set(item) == {"tag_id", "description", "score"},
                "invalid output fields")
        tag_id = item["tag_id"]
        require(isinstance(tag_id, str) and tag_id in by_id, "unknown output tag")
        require(tag_id not in seen, "duplicate output tag")
        seen.add(tag_id)
        tag = by_id[tag_id]
        family = data["families"][tag["family"]]
        allowed_objects = family.get("object_types", [family.get("object_type")])
        require(family["kind"] == "scored_state" and stage in family["stages"]
                and object_type in allowed_objects, "wrong tag scope")
        score = item["score"]
        require(type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1,
                "invalid normalized score")
        require(item["description"] == tag["description"], "noncanonical description")
    # ponytail: record validation only; simulation_policy_v1 selects from raw distributions.


def main():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    by_id = validate_registry(data)
    item = {"tag_id": "emotion.interest", "description": by_id["emotion.interest"]["description"],
            "score": 0.62}
    validate_selected(data, "A2", "article", [item])
    validate_selected(data, "A3", "article", [item])
    thought = by_id["thought.consider_later"]
    validate_selected(data, "B2", "product",
                      [{"tag_id": thought["id"], "description": thought["description"], "score": 0.7}])
    reason = by_id["attention_reason.repetition_fatigue"]
    validate_selected(data, "A1R", "article",
                      [{"tag_id": reason["id"], "description": reason["description"], "score": 0.81}])
    validate_selected(data, "B1R", "product",
                      [{"tag_id": reason["id"], "description": reason["description"], "score": 0.81}])
    validate_selected(data, "A2", "article", [])  # Empty does not mean indifference.
    invalid = [
        ("A1", "article", [item]),
        ("A2", "product", [item]),
        ("B2", "product", [item]),
        ("A2", "article", [item, item]),
        *[("A2", "article", [{**item, "score": score}])
          for score in (-0.1, 1.1, float("nan"), float("inf"), True, "0.5")],
        ("A2", "article", [{**item, "tag_id": "invented.tag"}]),
        ("A2", "article", [{**item, "description": "An invented definition."}]),
        ("A2", "article", [{**item, "action": "buy"}]),
        ("A2", "article", [{**item, "tag_id": "enterprise.craft_focus"}]),
        ("A1R", "article", [{**item, "tag_id": "emotion.interest"}]),
    ]
    for stage, object_type, tags in invalid:
        try:
            validate_selected(data, stage, object_type, tags)
        except ValueError:
            continue
        raise AssertionError("invalid fixture accepted")
    bad_registry = copy.deepcopy(data)
    bad_registry["tags"].append(bad_registry["tags"][0])
    try:
        validate_registry(bad_registry)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate registry tag accepted")
    print(f"PASS: {len(by_id)} tags, {len(data['families'])} families, {len(data['scales'])} draft scales")
    print(f"PASS: {len(invalid)} invalid selected-output fixtures and 1 invalid registry fixture rejected")
    print("PASS: valid and empty records accepted")


if __name__ == "__main__":
    main()

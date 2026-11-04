"""Validate the current stage-specific tag-to-persona context mapping."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "data/tags/agent_flow_tag_persona.mapping.v2.json"
TAGS = ROOT / "data/tags/agent_flow_tags.v2.json"
PERSONA = ROOT / "data/matraix/persona_1m/projectdut_persona.schema.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(mapping, tags, persona):
    require(mapping["version"] == "2.0-draft", "unexpected mapping version")
    require(mapping["language"] == "en", "mapping descriptions must be English")
    require(mapping["tag_registry_version"] == tags["version"], "tag version mismatch")
    require(mapping["persona_schema_version"] == persona["format_version"],
            "persona schema version mismatch")

    tag_by_id = {tag["id"]: tag for tag in tags["tags"]}
    input_families = {
        family for family, definition in tags["families"].items()
        if definition["kind"] == "input_description"
    }
    persona_by_id = {column["id"]: column for column in persona["columns"]}
    require(persona_by_id, "persona schema has no columns")

    stage_policy = mapping["stage_policy"]
    expected_stages = {"A1", "A1R", "A2", "A3", "A4", "A5",
                       "B1", "B1R", "B2", "B3"}
    require(set(stage_policy) == expected_stages, "stage policy drift")

    for stage, policy in stage_policy.items():
        require(policy["mode"] in {"select", "reuse", "none"},
                f"invalid mode for {stage}")
        if policy["mode"] == "select":
            require(policy["families"], f"empty family list for {stage}")
            require(set(policy["families"]) <= input_families,
                    f"non-input family used by {stage}")
            require(all(stage in tags["families"][family]["stages"]
                        for family in policy["families"]), f"family stage mismatch: {stage}")
            for field_id in policy["base_fields"]:
                require(field_id in persona_by_id,
                        f"unknown base field {field_id} in {stage}")
        elif policy["mode"] == "reuse":
            require(policy["from_stage"] in stage_policy,
                    f"invalid reuse source for {stage}")
            require(stage_policy[policy["from_stage"]]["mode"] == "select",
                    f"reuse source is not a select stage for {stage}")
        else:
            require("base_fields" not in policy,
                    f"none stage must not select fields: {stage}")

    rule_ids = [rule["tag_id"] for rule in mapping["rules"]]
    require(len(rule_ids) == len(set(rule_ids)), "duplicate mapping rule")
    expected_rule_ids = {
        tag_id for tag_id, tag in tag_by_id.items()
        if tag["family"] in input_families
    }
    require(set(rule_ids) == expected_rule_ids,
            "mapping rules must cover every input-description tag exactly once")

    for rule in mapping["rules"]:
        tag_id = rule["tag_id"]
        require(tag_id in tag_by_id, f"unknown tag in mapping: {tag_id}")
        require(tag_by_id[tag_id]["family"] in input_families,
                f"state tag mapped as input: {tag_id}")
        require(isinstance(rule["fields"], list), f"fields must be a list: {tag_id}")
        require(len(rule["fields"]) == len(set(rule["fields"])),
                f"duplicate fields for {tag_id}")
        for field_id in rule["fields"]:
            require(field_id in persona_by_id,
                    f"unknown persona field {field_id} for {tag_id}")
        require(rule["rationale"].strip() and rule["boundary"].strip(),
                f"missing rationale/boundary: {tag_id}")

    # State tags are outputs, not persona-to-context mappings in this version.
    state_families = {"thought", "emotion", "attention_reason"}
    require(not (set(rule_ids) & {
        tag_id for tag_id, tag in tag_by_id.items()
        if tag["family"] in state_families
    }), "state tag must not appear in input mapping rules")

    # Deterministic ordering is part of the context contract.
    for stage, policy in stage_policy.items():
        if policy["mode"] == "select":
            require(policy["base_fields"] == list(dict.fromkeys(policy["base_fields"])),
                    f"duplicate or unstable base fields in {stage}")
    require(mapping["principles"], "mapping principles are required")

def select_example(mapping, tags, persona, stage, assignments, values):
    """Offline reference for select stages; not a runtime prompt builder."""
    require(stage in mapping["stage_policy"], "unknown stage")
    policy = mapping["stage_policy"][stage]
    require(policy["mode"] == "select", "stage must reuse its snapshot or omit persona")
    require(isinstance(assignments, list) and isinstance(values, dict), "invalid input")
    by_tag = {tag["id"]: tag for tag in tags["tags"]}
    rules = {rule["tag_id"]: rule for rule in mapping["rules"]}
    columns = {column["id"]: column for column in persona["columns"]}
    active = set()
    for assignment in assignments:
        require(isinstance(assignment, dict), "invalid tag assignment")
        tag_id = assignment.get("tag_id")
        require(isinstance(tag_id, str) and tag_id in rules, "unknown or state tag")
        require(isinstance(assignment.get("source_ref"), str)
                and assignment["source_ref"].strip(), "missing evidence reference")
        visibility = assignment.get("visible_stages")
        family = by_tag[tag_id]["family"]
        require(isinstance(visibility, list) and
                all(s in tags["families"][family]["stages"] for s in visibility),
                "invalid tag visibility")
        if stage in visibility:
            require(family in policy["families"], "wrong input family for stage")
            active.add(tag_id)
    fields = list(policy["base_fields"])
    for tag_id in sorted(active):
        fields.extend(rules[tag_id]["fields"])
    result = []
    for field_id in dict.fromkeys(fields):
        value = values.get(field_id)
        if value is None:
            continue
        column = columns[field_id]
        require(isinstance(value, str) and value in column["values"], "invalid enum value")
        result.append({"field_id": field_id, "description": column["description"],
                       "value": value})
    # ponytail: visibility is supplied by a trusted caller; verify source ownership,
    # scenario scope and reuse snapshot identity when a runtime context builder exists.
    return result


def main():
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    tags = json.loads(TAGS.read_text(encoding="utf-8"))
    persona = json.loads(PERSONA.read_text(encoding="utf-8"))
    validate(mapping, tags, persona)
    source = json.loads((PERSONA.parent / "persona_codes.schema.json").read_text(encoding="utf-8"))
    originals = {column["id"]: column for column in source["columns"]}
    for column in persona["columns"]:
        require(all(column[k] == originals[column["id"]][k]
                    for k in ("id", "label", "category", "values")), "source schema drift")

    assignment = {"tag_id": "article.product_introduction",
                  "source_ref": "post_01.preview", "visible_stages": ["A1", "A2"]}
    values = {"trait_curiosity": "Strong", "att_advertising": "Neutral",
              "pref_novelty_vs_familiarity": "Novelty-leaning",
              "cog_attention_span": None, "topic_coffee": "Passionate"}
    select = lambda stage, assignments, values: select_example(
        mapping, tags, persona, stage, assignments, values)
    result = select("A1", [assignment], values)
    assert [f["field_id"] for f in result] == [
        "att_advertising", "trait_curiosity", "pref_novelty_vs_familiarity"]
    assert select("A1", [assignment, assignment], values) == result
    assert select("A1", [assignment], {}) == []
    offer = {"tag_id": "article.offer", "source_ref": "post_01.body",
             "visible_stages": ["A3"]}
    assert select("A1", [assignment, offer], {**values, "economic_motivation": "Cost-sensitive"}) == result
    visible_offer = {**offer, "source_ref": "post_01.preview", "visible_stages": ["A1"]}
    assert select("A1", [visible_offer, assignment], values) == select(
        "A1", [assignment, visible_offer], values)
    coffee = {"tag_id": "product.coffee_drink", "source_ref": "product_01.preview",
              "visible_stages": ["B1", "B2"]}
    caffeine = select("B1", [coffee], {"lstyle_caffeine": "None"})
    assert len(caffeine) == 1 and caffeine[0]["value"] == "None"
    sweet = {**coffee, "tag_id": "product.sweet_profile"}
    assert select("B1", [sweet], {"topic_coffee": "Passionate"}) == []

    invalid = [
        ("A1", [assignment], {**values, "trait_curiosity": "Invented"}),
        ("A1", [assignment], {**values, "trait_curiosity": 1}),
        ("A1", [{**assignment, "tag_id": "emotion.interest"}], values),
        ("A1", [{**assignment, "tag_id": "unknown.tag"}], values),
        ("A1", [{**assignment, "source_ref": ""}], values),
        ("A1", [{**assignment, "visible_stages": ["B1"]}], values),
        ("A3", [assignment], values),
        ("A1R", [assignment], values),
        ("unknown", [assignment], values),
    ]
    for args in invalid:
        try:
            select(*args)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid context accepted: {args}")
    bad = copy.deepcopy(mapping)
    bad["rules"][0]["fields"] = ["nonexistent_field"]
    try:
        validate(bad, tags, persona)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown field in mapping accepted")
    used = {f for rule in mapping["rules"] for f in rule["fields"]}
    used.update(f for p in mapping["stage_policy"].values() for f in p.get("base_fields", []))
    print(f"PASS: {len(mapping['rules'])} input tags covered; {len(used)} distinct candidate fields")
    print(f"PASS: {len(persona['columns'])} persona fields checked against source enums")
    print("PASS: synthetic context checks for visibility, order, deduplication, missing data and None")
    print(f"PASS: {len(invalid)} intentionally invalid contexts and 1 invalid mapping rejected")


if __name__ == "__main__":
    main()

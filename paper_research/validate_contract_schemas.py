"""Validate the internal JEV/LLM output schema and representative fixtures."""
import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "data/contracts/agent_model_output.schema.json"
TAGS_PATH = ROOT / "data/tags/agent_flow_tags.v2.json"


def expect_valid(validator, instance, label):
    errors = sorted(validator.iter_errors(instance), key=lambda error: error.path)
    if errors:
        raise AssertionError(f"{label} rejected: {errors[0].message}")


def expect_invalid(validator, instance, label):
    if not any(validator.iter_errors(instance)):
        raise AssertionError(f"{label} was accepted")


def semantic_validate(instance, tags):
    """Apply registry/stage rules that JSON Schema cannot express compactly."""
    variant_by_stage = {
        "A1R": {"skip_reason"},
        "B1R": {"skip_reason"},
        "A2": {"first_attention", "repeat_attention"},
        "A3": {"first_read", "repeat_read"},
        "B2": {"first_consideration", "repeat_consideration"},
    }
    stage = instance["stage"]
    if instance["contract_kind"] == "tag_scores":
        if instance["contract_variant"] not in variant_by_stage[stage]:
            raise ValueError(f"wrong contract variant for {stage}")
    if instance["contract_kind"] != "tag_scores":
        return

    expected = {
        "A1R": ("attention_reason", "article"),
        "B1R": ("attention_reason", "product"),
        "A2": ("emotion", "article"),
        "A3": ("emotion", "article"),
        "B2": ("thought", "product"),
    }[stage]
    by_id = {item["id"]: item for item in tags["tags"]}
    for item in instance["selected_tags"]:
        tag = by_id.get(item["tag_id"])
        if tag is None:
            raise ValueError(f"unknown tag: {item['tag_id']}")
        family = tags["families"][tag["family"]]
        allowed_objects = family.get("object_types", [family.get("object_type")])
        if (tag["family"], expected[1]) != expected or expected[1] not in allowed_objects:
            raise ValueError(f"wrong tag scope for {stage}: {item['tag_id']}")
        if item["description"] != tag["description"]:
            raise ValueError(f"noncanonical description: {item['tag_id']}")


def main():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    tags = json.loads(TAGS_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    def base(kind, stage, variant, source="jev"):
        return {
            "contract_version": "1.0-draft",
            "contract_kind": kind,
            "stage": stage,
            "contract_variant": variant,
            "status": "resolved",
            "source": source,
        }

    valid = []
    attention = base("attention_score", "A1", "first_encounter")
    attention.update({
        "attention": {
            "raw_score": 2.1,
            "normalized_score": 0.7,
            "scale_id": "attention_v1",
        },
        "decision": {
            "action": "attend",
            "policy_id": "attention_policy_v1",
        },
        "reason_state_ref": None,
    })
    valid.append(("first article attention", attention))

    repeat_attention = copy.deepcopy(attention)
    repeat_attention.update({
        "stage": "B1",
        "contract_variant": "repeat_product_encounter",
    })
    repeat_attention["decision"]["action"] = "skip"
    valid.append(("repeat product skip", repeat_attention))

    by_id = {item["id"]: item for item in tags["tags"]}

    def tag_output(stage, variant, tag_id):
        output = base("tag_scores", stage, variant, "llm_fallback")
        output.update({
            "selected_tags": [{
                "tag_id": tag_id,
                "description": by_id[tag_id]["description"],
                "score": 0.81,
            }],
            "normalization_policy_id": "normalization_v1",
            "selection_policy_id": "selection_v1",
        })
        return output

    valid.extend([
        ("article skip reason", tag_output(
            "A1R", "skip_reason", "attention_reason.repetition_fatigue")),
        ("initial article emotion", tag_output(
            "A2", "first_attention", "emotion.interest")),
        ("product thought", tag_output(
            "B2", "first_consideration", "thought.consider_later")),
    ])

    valid.extend([
        ("first reaction", {
            **base("choice", "A4", "first_reaction"),
            "answer": "no_reaction",
        }),
        ("existing reaction", {
            **base("choice", "A4", "existing_reaction"),
            "answer": "no_new_reaction",
        }),
        ("repeat purchase", {
            **base("choice", "B3", "repeat_purchase"),
            "answer": "not_buy_again",
        }),
        ("unresolved", {
            "contract_version": "1.0-draft",
            "contract_kind": "unresolved",
            "stage": "A2",
            "contract_variant": "repeat_attention",
            "status": "unresolved",
            "reason_code": "fallback_exhausted",
            "dependent_branch": "stop",
        }),
        ("empty result", {
            "contract_version": "1.0-draft",
            "contract_kind": "empty_result",
            "stage": "A2",
            "contract_variant": "repeat_attention",
            "status": "empty_result",
            "source": "llm_fallback",
            "selected_tags": [],
            "normalization_policy_id": "normalization_v1",
            "selection_policy_id": "simulation-policy-v1",
            "reason_code": "no_item_above_score_floor",
        }),
    ])

    for label, instance in valid:
        expect_valid(validator, instance, label)
        semantic_validate(instance, tags)

    invalid_schema = []
    wrong_attention_action = copy.deepcopy(attention)
    wrong_attention_action["contract_variant"] = "repeat_encounter"
    invalid_schema.append(("wrong repeat attention action", wrong_attention_action))

    wrong_purchase_action = {
        **base("choice", "B3", "repeat_purchase"),
        "answer": "buy",
    }
    invalid_schema.append(("wrong repeat purchase answer", wrong_purchase_action))

    invalid_schema.append(("score above one", {
        **base("tag_scores", "A2", "first_attention"),
        "selected_tags": [{
            "tag_id": "emotion.interest",
            "description": by_id["emotion.interest"]["description"],
            "score": 1.1,
        }],
    }))

    invalid_schema.append(("empty selected tags", {
        **base("tag_scores", "A2", "first_attention"),
        "selected_tags": [],
    }))

    extra_field = copy.deepcopy(attention)
    extra_field["unexpected"] = True
    invalid_schema.append(("unexpected field", extra_field))

    invalid_schema.append(("bad unresolved reason", {
        "contract_version": "1.0-draft",
        "contract_kind": "unresolved",
        "stage": "A2",
        "contract_variant": "first_attention",
        "status": "unresolved",
        "reason_code": "invented_reason",
    }))
    invalid_schema.append(("empty result with a tag", {
        "contract_version": "1.0-draft",
        "contract_kind": "empty_result",
        "stage": "A2",
        "contract_variant": "first_attention",
        "status": "empty_result",
        "source": "jev",
        "selected_tags": [{
            "tag_id": "emotion.interest",
            "description": by_id["emotion.interest"]["description"],
            "score": 0.2,
        }],
        "normalization_policy_id": "normalization_v1",
        "selection_policy_id": "simulation-policy-v1",
        "reason_code": "no_item_above_score_floor",
    }))

    for label, instance in invalid_schema:
        expect_invalid(validator, instance, label)

    wrong_scope = tag_output("A1R", "skip_reason", "emotion.interest")
    expect_valid(validator, wrong_scope, "schema accepts tag shape")
    try:
        semantic_validate(wrong_scope, tags)
    except ValueError:
        pass
    else:
        raise AssertionError("wrong tag scope was accepted by semantic validator")

    print(f"PASS: {len(valid)} valid contract fixtures accepted")
    print(f"PASS: {len(invalid_schema)} invalid schema fixtures rejected")
    print("PASS: registry stage, family, object, and canonical-description rules enforced")


if __name__ == "__main__":
    main()

"""Validate mapping references and coverage; run with Python 3, no dependencies."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "data/tags/projectdut_cafe_tag_persona.mapping.json"
TAGS = ROOT / "data/tags/projectdut_cafe_tags.schema.json"
PERSONA = ROOT / "data/matraix/persona_1m/projectdut_persona.schema.json"
FLOWS = {
    "article": "article_thought",
    "product": "product_thought",
    "enterprise": "enterprise_context",
}


def validate(data, tags, persona):
    """Check structure and references, not empirical validity of the links."""
    assert data["format"] == "projectdut_tag_persona_mapping"
    assert data["format_version"] == 1
    assert data["status"] == "draft" and data["language"] == "en"
    definitions = {tag["id"]: tag for tag in tags["definitions"]}
    assert len(definitions) == len(tags["definitions"])
    fields = {field["id"] for field in persona["columns"]}
    assert len(fields) == len(persona["columns"])
    assert data["scope"] == {**FLOWS, "thought": "out_of_scope", "emotion": "out_of_scope"}
    for key, document, path in (
        ("tag_vocabulary", tags, TAGS),
        ("persona_schema", persona, PERSONA),
    ):
        assert data["references"][key] == {
            "path": path.relative_to(ROOT).as_posix(),
            "format_version": document["format_version"],
        }
    expected = {tag_id for tag_id, tag in definitions.items() if tag["family"] in FLOWS}
    seen = set()
    for item in data["mappings"]:
        assert set(item) == {"tag_id", "family", "flow", "status", "links", "limitations"}
        tag_id = item["tag_id"]
        assert tag_id in expected and tag_id not in seen, tag_id
        seen.add(tag_id)
        assert item["family"] == definitions[tag_id]["family"]
        assert item["flow"] == FLOWS[item["family"]]
        assert item["status"] in {"mapped", "no_available_field", "campaign_metadata"}
        assert isinstance(item["links"], list)
        assert bool(item["links"]) == (item["status"] == "mapped"), tag_id
        assert isinstance(item["limitations"], list) and item["limitations"]
        assert all(isinstance(note, str) and note.strip() for note in item["limitations"])
        if definitions[tag_id]["group"] == "campaign_role":
            assert item["status"] == "campaign_metadata" and not item["links"]
        else:
            assert item["status"] != "campaign_metadata"
        used = set()
        for link in item["links"]:
            assert set(link) == {"field_id", "priority", "reason"}
            assert link["field_id"] in fields and link["field_id"] not in used, tag_id
            used.add(link["field_id"])
            assert link["priority"] in {"primary", "supporting"}
            assert isinstance(link["reason"], str) and link["reason"].strip()
    assert seen == expected, f"Missing tags: {sorted(expected - seen)}"


def self_check(data, tags, persona):
    # ponytail: validate a static mapping only; add persona-specific selection
    # checks when a context selector and its ranking policy are specified.
    mapped_index = next(
        index for index, item in enumerate(data["mappings"])
        if item["status"] == "mapped"
    )
    cases = []
    changed = deepcopy(data)
    changed["mappings"].pop()
    cases.append(changed)
    changed = deepcopy(data)
    changed["mappings"].append(deepcopy(changed["mappings"][0]))
    cases.append(changed)
    changed = deepcopy(data)
    changed["mappings"][mapped_index]["links"][0]["field_id"] = "invented_persona_field"
    cases.append(changed)
    changed = deepcopy(data)
    changed["mappings"][mapped_index]["links"].append(
        deepcopy(changed["mappings"][mapped_index]["links"][0])
    )
    cases.append(changed)
    changed = deepcopy(data)
    changed["mappings"][mapped_index]["flow"] = "purchase_decision"
    cases.append(changed)
    changed = deepcopy(data)
    changed["mappings"][mapped_index]["links"][0]["priority"] = "buy"
    cases.append(changed)
    changed = deepcopy(data)
    changed["mappings"][mapped_index]["tag_id"] = "emotion_interested"
    cases.append(changed)
    changed = deepcopy(data)
    changed["mappings"][mapped_index]["links"][0]["purchase_probability"] = 0.9
    cases.append(changed)
    for index, invalid in enumerate(cases):
        try:
            validate(invalid, tags, persona)
        except (AssertionError, KeyError, TypeError):
            continue
        raise AssertionError(f"Invalid fixture accepted: {index}")
    print(f"PASS: {len(cases)} invalid fixtures rejected")


if __name__ == "__main__":
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    vocabulary = json.loads(TAGS.read_text(encoding="utf-8"))
    schema = json.loads(PERSONA.read_text(encoding="utf-8"))
    validate(mapping, vocabulary, schema)
    self_check(mapping, vocabulary, schema)
    counts = Counter(item["status"] for item in mapping["mappings"])
    linked = {link["field_id"] for item in mapping["mappings"] for link in item["links"]}
    print(f"PASS: {len(mapping['mappings'])} content tags, {len(linked)} referenced persona fields; {dict(counts)}")

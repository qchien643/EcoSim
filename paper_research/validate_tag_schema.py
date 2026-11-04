"""Validate the closed projectDut2026 tag vocabulary.

Run: python3 paper_research/validate_tag_schema.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/tags/projectdut_cafe_tags.schema.json"


def main():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    families = data["families"]
    definitions = {item["id"]: item for item in data["definitions"]}
    assert len(definitions) == len(data["definitions"]), "duplicate definition"
    grouped = set()
    for family_name, family in families.items():
        assert family["max_tags"] > 0
        for group_name, group in family["groups"].items():
            assert 0 < group["max_tags"] <= family["max_tags"]
            for tag_id in group["tags"]:
                assert tag_id not in grouped, f"duplicate tag: {tag_id}"
                grouped.add(tag_id)
                item = definitions.get(tag_id)
                assert item, f"missing definition: {tag_id}"
                assert item["family"] == family_name
                assert item["group"] == group_name
                assert item["description"]
    assert grouped == set(definitions)
    assert data["status"] == "draft"
    assert data["status_notes"]["persona_mapping"] == "draft_enterprise_content_tags"
    assert data["status_notes"]["persona_mapping_file"] == "projectdut_cafe_tag_persona.mapping.json"
    print(f"PASS: {len(grouped)} unique tags across {len(families)} families")


if __name__ == "__main__":
    main()

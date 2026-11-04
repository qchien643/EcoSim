"""Resolve managed industry assets once; consumers use the frozen bundle."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_bundle(industry_id, profile_version):
    from .industry_profile import profile_path
    path = profile_path(industry_id, profile_version)
    profile = json.loads(path.read_text(encoding="utf-8"))
    result = {"profile": profile}
    for name in ("persona_schema", "tag_registry", "persona_mapping"):
        asset = (path.parent / profile[name]["path"]).resolve()
        if not asset.is_relative_to(ROOT / "data"):
            raise ValueError("Industry asset must be inside the managed data directory")
        result[name] = json.loads(asset.read_text(encoding="utf-8"))
    for name, filename in (
        ("renderer", "context-rendering.v2.json"),
        ("policy", "simulation-policy.v1.json"),
        ("relationship_policy", "relationship-context-policy.v1.json"),
    ):
        result[name] = json.loads((ROOT / "data/contracts" / filename).read_text(encoding="utf-8"))
    validate_bundle(result, industry_id, profile_version)
    return result


def validate_bundle(bundle, industry_id, profile_version):
    required = {"profile", "persona_schema", "tag_registry", "persona_mapping",
                "renderer", "policy", "relationship_policy"}
    if not isinstance(bundle, dict) or not required <= bundle.keys():
        raise ValueError("Industry bundle is missing required assets")
    profile = bundle["profile"]
    if (profile.get("industry_id"), profile.get("profile_version")) != (industry_id, profile_version):
        raise ValueError("Industry bundle identity mismatch")
    columns = {item["id"]: item for item in bundle["persona_schema"]["columns"]}
    tags = {item["id"]: item for item in bundle["tag_registry"]["tags"]}
    if len(tags) != len(bundle["tag_registry"]["tags"]):
        raise ValueError("Duplicate tag ID")
    fields = set()
    for name in ("core_persona_fields", "domain_persona_fields", "grouping_fields"):
        fields.update(profile[name])
    if not fields <= columns.keys():
        raise ValueError("Industry contains unknown persona fields")
    mapping = bundle["persona_mapping"]
    for rule in mapping["rules"]:
        if rule["tag_id"] not in tags or not set(rule["fields"]) <= columns.keys():
            raise ValueError("Invalid tag-persona mapping")
    for stage, config in mapping["stage_policy"].items():
        if stage not in bundle["renderer"]["stage_rendering"]:
            raise ValueError("Mapping references unsupported stage")
        if not set(config.get("base_fields", [])) <= columns.keys():
            raise ValueError("Stage references unknown persona fields")
    if set(bundle["renderer"]["stage_rendering"]) != {
        "A1", "A1R", "A2", "A3", "A4", "A5", "B1", "B1R", "B2", "B3"
    }:
        raise ValueError("Unsupported stage contract")


def validate_persona(persona, bundle):
    columns = {item["id"]: item for item in bundle["persona_schema"]["columns"]}
    profile = bundle["profile"]
    allowed = set(profile["core_persona_fields"] + profile["domain_persona_fields"] +
                  profile["grouping_fields"])
    if not isinstance(persona, dict) or not set(persona) <= allowed:
        raise ValueError("Persona has unknown or unselected fields")
    for field, value in persona.items():
        if value is not None and (not isinstance(value, str) or value not in columns[field]["values"]):
            raise ValueError(f"Invalid persona enum for {field}")

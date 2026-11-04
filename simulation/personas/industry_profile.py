"""Load and validate industry profiles used by scenario validation."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any

from simulation.context.renderer import PERSONA, TAGS, MAPPING

ROOT = Path(__file__).resolve().parents[2]
PROFILE_ROOT = ROOT / "data" / "industries"
RUNTIME_ASSETS = {
    "persona_schema": ("data/matraix/persona_1m/projectdut_persona.schema.json", PERSONA),
    "tag_registry": ("data/tags/agent_flow_tags.v2.json", TAGS),
    "persona_mapping": ("data/tags/agent_flow_tag_persona.mapping.v2.json", MAPPING),
}


class IndustryProfileError(ValueError):
    """The selected industry profile is missing or internally inconsistent."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise IndustryProfileError(f"Cannot read industry profile asset: {path}") from error
    if not isinstance(value, dict):
        raise IndustryProfileError("Industry profile must be a JSON object.")
    return value


def profile_path(industry_id: str, profile_version: str) -> Path:
    for value in (industry_id, profile_version):
        if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", value):
            raise IndustryProfileError("Industry and profile IDs must be lowercase slugs.")
    path = (PROFILE_ROOT / industry_id / f"{profile_version}.json").resolve()
    if not path.is_relative_to(PROFILE_ROOT.resolve()):
        raise IndustryProfileError("Profile path is outside the industry directory.")
    return path


def load_profile(industry_id: str, profile_version: str) -> dict[str, Any]:
    profile = _read_json(profile_path(industry_id, profile_version))
    validate_profile(profile, expected_industry=industry_id,
                     expected_version=profile_version)
    return profile


def validate_profile(profile: dict[str, Any], *,
                     expected_industry: str | None = None,
                     expected_version: str | None = None) -> None:
    if not isinstance(profile, dict) or profile.get("format") != "projectdut_industry_profile":
        raise IndustryProfileError("Unexpected industry profile format.")
    industry_id = profile.get("industry_id")
    version = profile.get("profile_version")
    directory = profile_path(industry_id, version).parent
    if expected_industry is not None and industry_id != expected_industry:
        raise IndustryProfileError("Profile industry_id does not match scenario.")
    if expected_version is not None and version != expected_version:
        raise IndustryProfileError(
            "Profile profile_version does not match scenario."
        )

    if profile.get("language") != "en":
        raise IndustryProfileError("Profile descriptions must use English.")
    # ponytail: the renderer/gateway still use one installed asset bundle.
    # Reject other bundles until all consumers support profile-specific assets.
    for name, (runtime_path, installed) in RUNTIME_ASSETS.items():
        reference = _required_object(profile, name)
        path = (directory / _required_string(reference, "path", name)).resolve()
        if path != (ROOT / runtime_path).resolve():
            raise IndustryProfileError(f"Unsupported runtime asset: {name}")
        version_key = "format_version" if name == "persona_schema" else "version"
        if reference.get(version_key) != installed[version_key]:
            raise IndustryProfileError(f"Asset version mismatch: {name}")
        if _read_json(path) != installed:
            raise IndustryProfileError(f"Asset changed after runtime loading: {name}")
    if industry_id != TAGS["initial_industry"]:
        raise IndustryProfileError("The installed tag bundle does not support this industry.")
    persona, persona_mapping = PERSONA, MAPPING

    columns = {item["id"]: item for item in persona.get("columns", [])
               if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if not columns:
        raise IndustryProfileError("Persona schema contains no usable columns.")
    core = _string_list(profile, "core_persona_fields")
    domain = _string_list(profile, "domain_persona_fields")
    grouping = _string_list(profile, "grouping_fields")
    if set(core) & set(domain):
        raise IndustryProfileError("Core and domain persona fields must be disjoint.")
    allowed = set(core) | set(domain)
    for field_id in allowed | set(grouping):
        if field_id not in columns:
            raise IndustryProfileError(f"Unknown persona field in profile: {field_id}")

    stage_fields = profile.get("stage_base_fields")
    expected_base = {stage: policy["base_fields"]
                     for stage, policy in persona_mapping["stage_policy"].items()
                     if policy["mode"] == "select"}
    if stage_fields != expected_base:
        raise IndustryProfileError("stage_base_fields must match the installed mapping.")

    mapping_fields = set()
    for policy in persona_mapping.get("stage_policy", {}).values():
        mapping_fields.update(policy.get("base_fields", []))
    for rule in persona_mapping.get("rules", []):
        mapping_fields.update(rule.get("fields", []))
    if not mapping_fields <= allowed:
        unknown = sorted(mapping_fields - allowed)
        raise IndustryProfileError(
            "Industry profile omits fields referenced by persona mapping: "
            + ", ".join(unknown)
        )


def profile_snapshot(profile: dict[str, Any]) -> dict[str, Any]:
    """Pin definitions and asset content, not only mutable version labels."""
    def digest(value):
        return hashlib.sha256(json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")).hexdigest()
    return {
        "profile": profile,
        "asset_hashes": {name: digest(asset) for name, (_, asset) in RUNTIME_ASSETS.items()},
    }

def _required_object(data: dict[str, Any], field: str) -> dict[str, Any]:
    value = data.get(field)
    if not isinstance(value, dict):
        raise IndustryProfileError(f"{field} must be an object.")
    return value


def _required_string(data: dict[str, Any], field: str, owner: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise IndustryProfileError(f"{owner}.{field} must be a non-empty string.")
    return value


def _string_list(data: dict[str, Any], field: str) -> list[str]:
    value = data.get(field)
    if (not isinstance(value, list) or
            any(not isinstance(item, str) or not item.strip() for item in value)):
        raise IndustryProfileError(f"{field} must be a list of non-empty strings.")
    if len(value) != len(set(value)):
        raise IndustryProfileError(f"{field} must not contain duplicates.")
    return value

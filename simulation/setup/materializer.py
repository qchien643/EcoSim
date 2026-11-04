"""Resolve marketer scenario references into an immutable runnable snapshot."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


class ScenarioMaterializationError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScenarioMaterializationError(f"Cannot read JSON file: {path}") from error
    if not isinstance(value, dict):
        raise ScenarioMaterializationError(f"JSON file must contain an object: {path}")
    return value


def _resolve_path(value: Any, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ScenarioMaterializationError(f"{field} must be a non-empty path")
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise ScenarioMaterializationError(f"{field} does not exist: {value}")
    return path


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_cohort(reference: dict[str, Any], scenario: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cohort_path = _resolve_path(reference.get("cohort_path"), field="cohort_path")
    manifest_value = reference.get("manifest_path")
    manifest_path = (
        _resolve_path(manifest_value, field="manifest_path")
        if manifest_value is not None
        else cohort_path.with_name("manifest.json")
    )
    manifest = _read_json(manifest_path)
    if manifest.get("format") != "projectdut_persona_cohort":
        raise ScenarioMaterializationError("Unsupported persona cohort manifest format")
    if manifest.get("industry_id") != scenario.get("industry_id"):
        raise ScenarioMaterializationError("Persona cohort industry does not match scenario")
    if manifest.get("industry_profile_version") != scenario.get("industry_profile_version"):
        raise ScenarioMaterializationError(
            "Persona cohort industry profile does not match scenario"
        )
    rows: list[dict[str, Any]] = []
    try:
        with cohort_path.open(encoding="utf-8") as stream:
            for line_no, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ScenarioMaterializationError(
                        f"Invalid cohort JSON at line {line_no}"
                    ) from error
                if not isinstance(row, dict):
                    raise ScenarioMaterializationError(
                        f"Cohort row {line_no} must be an object"
                    )
                rows.append(row)
    except OSError as error:
        raise ScenarioMaterializationError(f"Cannot read cohort file: {cohort_path}") from error
    declared_size = manifest.get("size")
    if type(declared_size) is not int or declared_size != len(rows):
        raise ScenarioMaterializationError(
            "Cohort row count does not match manifest.size"
        )
    requested = reference.get("agent_count", declared_size)
    if type(requested) is not int or requested < 1 or requested > len(rows):
        raise ScenarioMaterializationError(
            "agent_count must be between 1 and the available cohort size"
        )
    selected = rows[:requested]
    seen: set[str] = set()
    for index, row in enumerate(selected, start=1):
        source_id = row.get("source_persona_id")
        persona = row.get("persona")
        cohort_id = row.get("cohort_persona_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ScenarioMaterializationError(
                f"Cohort row {index} has no source_persona_id"
            )
        if not isinstance(cohort_id, str) or not cohort_id.strip():
            raise ScenarioMaterializationError(
                f"Cohort row {index} has no cohort_persona_id"
            )
        if cohort_id in seen:
            raise ScenarioMaterializationError(f"Duplicate cohort_persona_id: {cohort_id}")
        if not isinstance(persona, dict) or not persona:
            raise ScenarioMaterializationError(
                f"Cohort row {index} has no persona object"
            )
        seen.add(cohort_id)
    snapshot = {
        "format": "projectdut_persona_cohort_snapshot",
        "cohort_path": _relative_path(cohort_path),
        "manifest_path": _relative_path(manifest_path),
        "cohort_sha256": _file_hash(cohort_path),
        "manifest_sha256": _file_hash(manifest_path),
        "manifest_size": declared_size,
        "selected_size": requested,
        "source_license_notice": manifest.get("research_license_notice"),
    }
    return selected, snapshot


def _agent_id(row: dict[str, Any]) -> str:
    return f"agent_{row['cohort_persona_id']}"


def _materialize_agents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agents = [
        {
            "agent_id": _agent_id(row),
            "source_persona_id": row["source_persona_id"],
            "persona": deepcopy(row["persona"]),
            "persona_provenance": deepcopy(row.get("provenance", {})),
            "field_provenance": deepcopy(row.get("field_provenance", {})),
            "cohort_bucket": row.get("cohort_bucket"),
        }
        for row in rows
    ]
    return sorted(agents, key=lambda item: item["agent_id"])


def _rounded_counts(groups: list[dict[str, Any]], total: int) -> list[int]:
    quotas = [
        Decimal(group["count"])
        if "count" in group
        else Decimal(str(group["percentage"])) * total / Decimal(100)
        for group in groups
    ]
    counts = [int(quota) for quota in quotas]
    remaining = total - sum(counts)
    order = sorted(
        range(len(groups)),
        key=lambda index: (-(quotas[index] - counts[index]), index),
    )
    for index in order[:remaining]:
        counts[index] += 1
    return counts


def _stable_rank(agent_id: str, seed: int) -> tuple[str, str]:
    digest = hashlib.sha256(
        f"scenario-customer-structure-v1|{seed}|{agent_id}".encode("utf-8")
    ).hexdigest()
    return digest, agent_id


def _materialize_customer_structure(
    scenario: dict[str, Any], agents: list[dict[str, Any]]
) -> dict[str, Any]:
    source = deepcopy(scenario.get("customer_structure"))
    if source is None:
        return {
            "total_agents": len(agents),
            "assignment_seed": 0,
            "groups": [{
                "group_id": "all_agents",
                "agent_ids": [agent["agent_id"] for agent in agents],
                "count": len(agents),
            }],
        }
    if not isinstance(source, dict):
        return source
    source.setdefault("total_agents", len(agents))
    source.setdefault("assignment_seed", 0)
    groups = source.get("groups")
    if not isinstance(groups, list) or not groups:
        return source
    if all(isinstance(group, dict) and "agent_ids" in group for group in groups):
        return source
    if any(not isinstance(group, dict) or "agent_ids" in group for group in groups):
        raise ScenarioMaterializationError(
            "customer_structure groups must either all omit agent_ids or all provide them"
        )
    seed = source["assignment_seed"]
    if type(seed) is not int or seed < 0:
        raise ScenarioMaterializationError("customer_structure.assignment_seed must be >= 0")
    ranked = sorted(
        (agent["agent_id"] for agent in agents),
        key=lambda agent_id: _stable_rank(agent_id, seed),
    )
    counts = _rounded_counts(groups, len(agents))
    cursor = 0
    for group, count in zip(groups, counts):
        group["agent_ids"] = ranked[cursor:cursor + count]
        cursor += count
    return source


def materialize_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Resolve cohort references while preserving already-resolved scenarios."""
    result = deepcopy(scenario)
    reference = result.get("persona_cohort")
    if reference is None:
        return result
    if not isinstance(reference, dict):
        raise ScenarioMaterializationError("persona_cohort must be an object")
    rows, cohort_snapshot = _load_cohort(reference, result)
    generated_agents = _materialize_agents(rows)
    supplied_agents = result.get("agents")
    if supplied_agents is not None:
        supplied_by_id = {
            agent.get("agent_id"): agent
            for agent in supplied_agents
            if isinstance(agent, dict)
        }
        generated_by_id = {agent["agent_id"]: agent for agent in generated_agents}
        if supplied_by_id != generated_by_id:
            raise ScenarioMaterializationError(
                "Resolved agents conflict with persona_cohort materialization"
            )
    result["agents"] = generated_agents
    result["customer_structure"] = _materialize_customer_structure(
        result, generated_agents
    )
    supplied_snapshot = result.get("persona_cohort_snapshot")
    if supplied_snapshot is not None and supplied_snapshot != cohort_snapshot:
        raise ScenarioMaterializationError(
            "persona_cohort_snapshot does not match the current cohort files"
        )
    result["persona_cohort_snapshot"] = cohort_snapshot
    return result

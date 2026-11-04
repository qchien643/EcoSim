"""Load, validate and canonicalize marketer scenario input."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from simulation.personas.assignment import materialize_relationships
from .materializer import materialize_scenario
from .validator import SCENARIO_VERSION, ScenarioValidationError, ScenarioValidator


class ScenarioLoader:
    """Create the immutable, deterministic input shape consumed by the runner."""

    def __init__(self, validator: ScenarioValidator | None = None):
        self.validator = validator or ScenarioValidator()

    def load(self, source: Mapping[str, Any] | str | Path) -> dict[str, Any]:
        scenario = materialize_scenario(self._read(source))
        issues = self.validator.validate(scenario)
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            raise ScenarioValidationError(errors)
        result = self._canonicalize(scenario, issues)
        result["relationship_assignments"] = materialize_relationships(result)
        result["industry_profile_snapshot"] = copy.deepcopy(
            self.validator.industry_profile_snapshot
        )
        return result

    @staticmethod
    def _read(source: Mapping[str, Any] | str | Path) -> dict[str, Any]:
        if isinstance(source, Mapping):
            return copy.deepcopy(dict(source))
        path = Path(source)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid scenario JSON: {path}") from error
        if not isinstance(value, dict):
            raise ValueError("Scenario file must contain a JSON object.")
        return value

    @staticmethod
    def _canonicalize(scenario: dict[str, Any],
                      issues: list[Any]) -> dict[str, Any]:
        result = copy.deepcopy(scenario)
        result.setdefault("policy_version", "simulation-policy-v1")
        result["scenario_schema_version"] = SCENARIO_VERSION
        result["validation_warnings"] = [
            issue.as_dict() for issue in issues if issue.severity == "warning"
        ]
        result["sessions"] = sorted(
            result["sessions"], key=lambda item: (item["session_no"], item["session_id"])
        )
        result["agents"] = sorted(
            result["agents"], key=lambda item: item["agent_id"]
        )
        result["shops"] = sorted(
            result["shops"], key=lambda item: item["shop_id"]
        )
        result["posts"] = sorted(
            result["posts"], key=lambda item: item["post_id"]
        )
        result["products"] = sorted(
            result["products"],
            key=lambda item: (item["shop_id"], item["position"], item["product_id"]),
        )
        for session in result["sessions"]:
            session["posts"] = sorted(
                session.get("posts", []),
                key=lambda item: (item["position"], item["post_id"]),
            )
            if "active_agents" in session:
                session["active_agents"] = sorted(session["active_agents"])
        return result

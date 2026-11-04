"""Seeded assignment of agent-to-brand relationship state."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
from typing import Any, Iterable

RELATIONSHIP_POLICY_VERSION = "relationship-assignment-v1"
RELATIONSHIP_FIELDS = (
    "awareness",
    "familiarity",
    "attitude",
    "purchase_history",
)
RELATIONSHIP_VALUES = {
    "awareness": {"unknown", "aware"},
    "familiarity": {"none", "low", "established"},
    "attitude": {"not_formed", "positive", "neutral", "negative"},
    "purchase_history": {"none", "has_purchased"},
}


@dataclass(frozen=True)
class RelationshipIssue:
    path: str
    code: str
    message: str


class RelationshipAssignmentError(ValueError):
    def __init__(self, issues: list[RelationshipIssue]):
        self.issues = issues
        message = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        super().__init__(message)


def default_relationship() -> dict[str, str]:
    return {
        "awareness": "unknown",
        "familiarity": "none",
        "attitude": "not_formed",
        "purchase_history": "none",
    }


def validate_relationship_state(state: Any, path: str = "$") -> list[RelationshipIssue]:
    issues: list[RelationshipIssue] = []
    if not isinstance(state, dict):
        return [RelationshipIssue(path, "STATE_NOT_OBJECT",
                                  "Relationship state must be an object.")]
    if set(state) != set(RELATIONSHIP_FIELDS):
        issues.append(RelationshipIssue(
            path, "STATE_SHAPE",
            "Relationship state must contain exactly awareness, familiarity, "
            "attitude and purchase_history.",
        ))
        return issues
    for field in RELATIONSHIP_FIELDS:
        if state[field] not in RELATIONSHIP_VALUES[field]:
            issues.append(RelationshipIssue(
                f"{path}.{field}", "INVALID_STATE_VALUE",
                f"Value must be one of {sorted(RELATIONSHIP_VALUES[field])}.",
            ))
    if issues:
        return issues
    awareness = state["awareness"]
    familiarity = state["familiarity"]
    attitude = state["attitude"]
    purchase_history = state["purchase_history"]
    if awareness == "unknown" and state != default_relationship():
        issues.append(RelationshipIssue(
            path, "INVALID_UNKNOWN_COMBINATION",
            "An unknown brand must have no familiarity, no formed attitude "
            "and no purchase history.",
        ))
    if familiarity == "none" and purchase_history != "none":
        issues.append(RelationshipIssue(
            path, "INVALID_PURCHASE_WITHOUT_FAMILIARITY",
            "A prior purchase requires at least low familiarity.",
        ))
    if familiarity == "established" and awareness != "aware":
        issues.append(RelationshipIssue(
            path, "INVALID_ESTABLISHED_AWARENESS",
            "Established familiarity requires brand awareness.",
        ))
    if purchase_history == "has_purchased" and (
        awareness != "aware" or familiarity != "established"
    ):
        issues.append(RelationshipIssue(
            path, "INVALID_PURCHASE_HISTORY",
            "A prior purchase requires awareness and established familiarity; "
            "it does not imply a formed attitude.",
        ))
    return issues


def _allocation_counts(groups: list[dict[str, Any]], total: int) -> list[int]:
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


def validate_initialization(
    initialization: Any,
    agent_ids: Iterable[str],
    path: str = "$.relationship_initialization",
) -> list[RelationshipIssue]:
    """Validate marketer input before assigning any agent."""
    issues: list[RelationshipIssue] = []
    known_agents = list(agent_ids)
    if not isinstance(initialization, dict):
        return [RelationshipIssue(path, "INITIALIZATION_NOT_OBJECT",
                                  "relationship_initialization must be an object.")]
    seed = initialization.get("seed")
    if type(seed) is not int or seed < 0:
        issues.append(RelationshipIssue(
            f"{path}.seed", "INVALID_SEED", "seed must be an integer >= 0.",
        ))
    groups = initialization.get("groups")
    if not isinstance(groups, list) or not groups:
        issues.append(RelationshipIssue(
            f"{path}.groups", "GROUPS_REQUIRED",
            "At least one relationship group is required.",
        ))
        return issues
    modes: set[str] = set()
    group_ids: set[str] = set()
    for index, group in enumerate(groups):
        group_path = f"{path}.groups[{index}]"
        if not isinstance(group, dict):
            issues.append(RelationshipIssue(group_path, "GROUP_NOT_OBJECT",
                                            "Each relationship group must be an object."))
            continue
        if set(group) != {"group_id", "state", "count"} and \
                set(group) != {"group_id", "state", "percentage"}:
            issues.append(RelationshipIssue(
                group_path, "GROUP_SHAPE",
                "A group must contain group_id, state and exactly one of count "
                "or percentage.",
            ))
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or not group_id.strip():
            issues.append(RelationshipIssue(
                f"{group_path}.group_id", "GROUP_ID_REQUIRED",
                "group_id must be a non-empty string.",
            ))
        elif group_id in group_ids:
            issues.append(RelationshipIssue(
                f"{group_path}.group_id", "DUPLICATE_GROUP_ID",
                "group_id must be unique.",
            ))
        group_ids.add(group_id)
        issues.extend(validate_relationship_state(group.get("state"),
                                                  f"{group_path}.state"))
        has_count = "count" in group
        has_percentage = "percentage" in group
        if has_count == has_percentage:
            continue
        mode = "count" if has_count else "percentage"
        modes.add(mode)
        value = group[mode]
        if mode == "count" and (type(value) is not int or value < 0):
            issues.append(RelationshipIssue(
                f"{group_path}.count", "INVALID_COUNT",
                "count must be an integer >= 0.",
            ))
        if mode == "percentage" and (
            type(value) not in (int, float) or not 0 <= value <= 100
        ):
            issues.append(RelationshipIssue(
                f"{group_path}.percentage", "INVALID_PERCENTAGE",
                "percentage must be between 0 and 100.",
            ))
    if len(modes) > 1:
        issues.append(RelationshipIssue(
            path, "MIXED_ALLOCATION_MODES",
            "Use count for every group or percentage for every group.",
        ))
    elif modes == {"count"} and sum(
        group.get("count", 0) for group in groups
        if isinstance(group, dict) and type(group.get("count")) is int
    ) != len(known_agents):
        issues.append(RelationshipIssue(
            path, "COUNT_SUM", "Group counts must equal the number of agents.",
        ))
    elif modes == {"percentage"} and abs(sum(
        float(group.get("percentage", 0)) for group in groups
        if isinstance(group, dict) and type(group.get("percentage")) in (int, float)
    ) - 100.0) > 1e-6:
        issues.append(RelationshipIssue(
            path, "PERCENTAGE_SUM", "Group percentages must sum to 100.",
        ))
    return issues


def _stable_rank(agent_id: str, seed: int) -> tuple[str, str]:
    digest = hashlib.sha256(f"{RELATIONSHIP_POLICY_VERSION}|{seed}|{agent_id}"
                            .encode("utf-8")).hexdigest()
    return digest, agent_id


def assign_relationships(
    agents: list[dict[str, Any]],
    initialization: dict[str, Any] | None = None,
    *,
    organization_id: str,
    brand_id: str,
) -> list[dict[str, Any]]:
    """Assign each resolved agent exactly one initial brand relationship."""
    agent_ids = [agent.get("agent_id") for agent in agents]
    issues: list[RelationshipIssue] = []
    if any(not isinstance(agent_id, str) or not agent_id.strip()
           for agent_id in agent_ids):
        issues.append(RelationshipIssue("$.agents", "AGENT_ID_REQUIRED",
                                        "Every agent must have a non-empty agent_id."))
    if len(set(agent_ids)) != len(agent_ids):
        issues.append(RelationshipIssue("$.agents", "DUPLICATE_AGENT_ID",
                                        "Agent IDs must be unique."))
    if initialization is None:
        initialization = {
            "seed": 0,
            "groups": [{
                "group_id": "default_unknown",
                "state": default_relationship(),
                "count": len(agent_ids),
            }],
        }
        defaulted = True
    else:
        defaulted = False
    issues.extend(validate_initialization(initialization, agent_ids))
    if issues:
        raise RelationshipAssignmentError(issues)

    seed = initialization["seed"]
    groups = initialization["groups"]
    counts = _allocation_counts(groups, len(agent_ids))
    ranked_agents = sorted(agent_ids, key=lambda agent_id: _stable_rank(agent_id, seed))
    assignments: list[dict[str, Any]] = []
    cursor = 0
    for group, count in zip(groups, counts):
        for position, agent_id in enumerate(ranked_agents[cursor:cursor + count], start=1):
            assignments.append({
                "agent_id": agent_id,
                "organization_id": organization_id,
                "brand_id": brand_id,
                "group_id": group["group_id"],
                "state": dict(group["state"]),
                "provenance": {
                    "policy_version": RELATIONSHIP_POLICY_VERSION,
                    "seed": seed,
                    "group_id": group["group_id"],
                    "allocation_mode": "count" if "count" in group else "percentage",
                    "allocation_value": group.get("count", group.get("percentage")),
                    "assignment_rank": cursor + position,
                    "defaulted": defaulted,
                },
            })
        cursor += count
    return sorted(assignments, key=lambda item: item["agent_id"])


def validate_assignments(
    assignments: Any,
    agent_ids: Iterable[str],
    *,
    organization_id: str,
    brand_id: str,
    path: str = "$.relationship_assignments",
) -> list[RelationshipIssue]:
    issues: list[RelationshipIssue] = []
    known = set(agent_ids)
    if not isinstance(assignments, list):
        return [RelationshipIssue(path, "ASSIGNMENTS_REQUIRED",
                                  "relationship_assignments must be a list.")]
    seen: set[str] = set()
    for index, assignment in enumerate(assignments):
        item_path = f"{path}[{index}]"
        if not isinstance(assignment, dict):
            issues.append(RelationshipIssue(item_path, "ASSIGNMENT_NOT_OBJECT",
                                            "Each assignment must be an object."))
            continue
        agent_id = assignment.get("agent_id")
        if agent_id in seen:
            issues.append(RelationshipIssue(
                f"{item_path}.agent_id", "DUPLICATE_ASSIGNMENT",
                "An agent may have only one assignment.",
            ))
        seen.add(agent_id)
        if agent_id not in known:
            issues.append(RelationshipIssue(
                f"{item_path}.agent_id", "UNKNOWN_AGENT",
                "Assignment refers to an agent outside the resolved scenario.",
            ))
        if assignment.get("organization_id") != organization_id or \
                assignment.get("brand_id") != brand_id:
            issues.append(RelationshipIssue(
                item_path, "RELATIONSHIP_OWNER_MISMATCH",
                "Assignment must target the scenario organization and brand.",
            ))
        issues.extend(validate_relationship_state(assignment.get("state"),
                                                  f"{item_path}.state"))
    if seen != known:
        issues.append(RelationshipIssue(
            path, "ASSIGNMENT_PARTITION",
            "Assignments must cover every resolved agent exactly once.",
        ))
    return issues


def materialize_relationships(
    scenario: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the canonical assignments that belong in a run snapshot."""
    assignments = assign_relationships(
        scenario["agents"],
        scenario.get("relationship_initialization"),
        organization_id=scenario["organization_id"],
        brand_id=scenario["brand_id"],
    )
    supplied = scenario.get("relationship_assignments")
    if supplied is not None:
        issues = validate_assignments(
            supplied,
            [agent["agent_id"] for agent in scenario["agents"]],
            organization_id=scenario["organization_id"],
            brand_id=scenario["brand_id"],
        )
        if issues:
            raise RelationshipAssignmentError(issues)
        if supplied != assignments:
            raise RelationshipAssignmentError([RelationshipIssue(
                "$.relationship_assignments", "ASSIGNMENT_DRIFT",
                "Supplied assignments do not match deterministic materialization.",
            )])
    return assignments

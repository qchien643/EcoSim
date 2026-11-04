"""Deterministic validation for marketer-provided simulation scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from simulation.context.renderer import BY_FIELD, BY_TAG, TAGS
from ..personas.industry_profile import IndustryProfileError, load_profile, profile_snapshot
from simulation.personas.assignment import (
    materialize_relationships,
    validate_assignments,
    validate_initialization,
)

SCENARIO_VERSION = "scenario-input-v1"
SCENARIO_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] /
     "data/contracts/scenario-input.v1.json").read_text(encoding="utf-8")
)
OWNER_FIELDS = {
    "shop": {"public_profile"},
    "post": {"preview", "article_content"},
    "product": {"product_name", "listed_price", "product_description"},
}
OWNER_FAMILIES = {"shop": "enterprise", "post": "article", "product": "product"}
ID_FIELDS = {
    "shops": "shop_id",
    "posts": "post_id",
    "products": "product_id",
}


@dataclass(frozen=True)
class ScenarioIssue:
    path: str
    code: str
    message: str
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


class ScenarioValidationError(ValueError):
    def __init__(self, issues: list[ScenarioIssue]):
        self.issues = issues
        message = "; ".join(f"{item.path}: {item.message}" for item in issues)
        super().__init__(message)


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


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


class ScenarioValidator:
    """Validate the resolved v1 scenario shape before creating a run."""

    def validate(self, scenario: Any) -> list[ScenarioIssue]:
        self.issues: list[ScenarioIssue] = []
        self.industry_profile_snapshot = None
        if not isinstance(scenario, dict):
            return [ScenarioIssue("$", "SCENARIO_NOT_OBJECT",
                                  "Scenario must be a JSON object.")]

        for field in ("run_id", "scenario_id", "campaign_id",
                      "organization_id", "brand_id", "industry_id",
                      "industry_profile_version"):
            self._required_string(scenario, field, "$")

        for error in Draft202012Validator(SCENARIO_SCHEMA).iter_errors(scenario):
            path = "$" + "".join(
                f"[{part}]" if isinstance(part, int) else f".{part}"
                for part in error.absolute_path
            )
            self._error(path, f"SCHEMA_{error.validator.upper()}",
                        error.message)
        if self.issues:
            return self.issues

        self._optional_string(scenario, "policy_version", "$")
        self._optional_int(scenario, "session_count", "$", minimum=1)
        profile = None
        try:
            profile = load_profile(
                scenario["industry_id"], scenario["industry_profile_version"]
            )
            self.industry_profile_snapshot = profile_snapshot(profile)
            if ("industry_profile_snapshot" in scenario and
                    scenario["industry_profile_snapshot"] != self.industry_profile_snapshot):
                self._error(
                    "$.industry_profile_snapshot", "INDUSTRY_PROFILE_DRIFT",
                    "Profile or assets differ from the frozen snapshot; restore the "
                    "original bundle to resume, or create a new run.",
                )
        except IndustryProfileError as error:
            self._error(
                "$.industry_profile_version",
                "INVALID_INDUSTRY_PROFILE",
                str(error),
            )
            return self.issues

        sessions = self._required_list(scenario, "sessions", "$", minimum=1)
        agents = self._required_list(scenario, "agents", "$", minimum=1)
        shops = self._required_list(scenario, "shops", "$", minimum=1)
        posts = self._required_list(scenario, "posts", "$", minimum=0)
        products = self._required_list(scenario, "products", "$", minimum=0)

        self._validate_sessions(scenario, sessions, agents, posts)
        self._validate_agents(agents, profile)
        shop_ids = self._validate_shops(scenario, shops)
        post_ids = self._validate_posts(scenario, posts, shop_ids)
        self._validate_products(scenario, products, shop_ids)
        self._validate_customer_structure(scenario, agents)
        self._validate_relationships(scenario, agents)

        if isinstance(scenario.get("session_count"), int):
            if scenario["session_count"] != len(sessions):
                self._error(
                    "session_count", "SESSION_COUNT_MISMATCH",
                    "session_count must equal the number of session records.",
                )
        if not post_ids and not posts:
            self._warning(
                "posts", "NO_POSTS",
                "Scenario contains no posts; sessions will still run but no "
                "article flow can start.",
            )
        return self.issues

    def validate_or_raise(self, scenario: Any) -> None:
        issues = self.validate(scenario)
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            raise ScenarioValidationError(errors)

    def _error(self, path: str, code: str, message: str) -> None:
        self.issues.append(ScenarioIssue(path, code, message))

    def _warning(self, path: str, code: str, message: str) -> None:
        self.issues.append(ScenarioIssue(path, code, message, "warning"))

    def _required_string(self, data: dict[str, Any], field: str, path: str) -> None:
        if not _is_nonempty_string(data.get(field)):
            self._error(f"{path}.{field}", "REQUIRED_STRING",
                        "A non-empty string is required.")

    def _optional_string(self, data: dict[str, Any], field: str, path: str) -> None:
        if field in data and not _is_nonempty_string(data[field]):
            self._error(f"{path}.{field}", "INVALID_STRING",
                        "The value must be a non-empty string.")

    def _optional_int(self, data: dict[str, Any], field: str, path: str,
                      minimum: int) -> None:
        if field in data and (type(data[field]) is not int or data[field] < minimum):
            self._error(f"{path}.{field}", "INVALID_INTEGER",
                        f"The value must be an integer >= {minimum}.")

    def _required_list(self, data: dict[str, Any], field: str, path: str,
                       minimum: int) -> list[Any]:
        value = data.get(field)
        if not isinstance(value, list):
            self._error(f"{path}.{field}", "REQUIRED_LIST",
                        "A list is required.")
            return []
        if len(value) < minimum:
            self._error(f"{path}.{field}", "LIST_TOO_SHORT",
                        f"The list must contain at least {minimum} item(s).")
        return value

    def _validate_unique_ids(self, items: list[Any], field: str, path: str) -> set[str]:
        ids: set[str] = set()
        for index, item in enumerate(items):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                self._error(item_path, "ITEM_NOT_OBJECT",
                            "Each item must be an object.")
                continue
            value = item.get(field)
            if not _is_nonempty_string(value):
                self._error(f"{item_path}.{field}", "REQUIRED_STRING",
                            "A non-empty identifier is required.")
                continue
            if value in ids:
                self._error(f"{item_path}.{field}", "DUPLICATE_ID",
                            f"Identifier {value!r} is duplicated.")
            ids.add(value)
        return ids

    def _validate_sessions(self, scenario: dict[str, Any], sessions: list[Any],
                           agents: list[Any], posts: list[Any]) -> None:
        session_ids = self._validate_unique_ids(sessions, "session_id", "$.sessions")
        session_nos: list[int] = []
        agent_ids = {
            item.get("agent_id") for item in agents
            if isinstance(item, dict) and _is_nonempty_string(item.get("agent_id"))
        }
        post_ids = {
            item.get("post_id") for item in posts
            if isinstance(item, dict) and _is_nonempty_string(item.get("post_id"))
        }
        for index, session in enumerate(sessions):
            path = f"$.sessions[{index}]"
            if not isinstance(session, dict):
                continue
            session_no = session.get("session_no")
            if type(session_no) is not int or session_no < 1:
                self._error(f"{path}.session_no", "INVALID_SESSION_NUMBER",
                            "session_no must be a positive integer.")
            else:
                session_nos.append(session_no)
            active_agents = session.get("active_agents")
            if active_agents is not None:
                if not isinstance(active_agents, list):
                    self._error(f"{path}.active_agents", "INVALID_AGENT_LIST",
                                "active_agents must be a list when supplied.")
                else:
                    if len(set(active_agents)) != len(active_agents):
                        self._error(f"{path}.active_agents", "DUPLICATE_AGENT",
                                    "An agent may appear only once in a session.")
                    for agent_index, agent_id in enumerate(active_agents):
                        if agent_id not in agent_ids:
                            self._error(
                                f"{path}.active_agents[{agent_index}]",
                                "UNKNOWN_AGENT",
                                f"Agent {agent_id!r} is not defined.",
                            )
            scheduled = session.get("posts", [])
            if not isinstance(scheduled, list):
                self._error(f"{path}.posts", "INVALID_POST_SCHEDULE",
                            "posts must be a list.")
                continue
            positions: set[int] = set()
            scheduled_ids: set[str] = set()
            for post_index, entry in enumerate(scheduled):
                entry_path = f"{path}.posts[{post_index}]"
                if not isinstance(entry, dict):
                    self._error(entry_path, "ITEM_NOT_OBJECT",
                                "A scheduled post must be an object.")
                    continue
                post_id = entry.get("post_id")
                position = entry.get("position")
                if post_id not in post_ids:
                    self._error(f"{entry_path}.post_id", "UNKNOWN_POST",
                                f"Post {post_id!r} is not defined.")
                if post_id in scheduled_ids:
                    self._error(f"{entry_path}.post_id", "DUPLICATE_SESSION_POST",
                                "A post may appear only once in one session.")
                scheduled_ids.add(post_id)
                if type(position) is not int or position < 1:
                    self._error(f"{entry_path}.position", "INVALID_POSITION",
                                "position must be a positive integer.")
                elif position in positions:
                    self._error(f"{entry_path}.position", "DUPLICATE_POSITION",
                                "position must be unique within one session.")
                else:
                    positions.add(position)
        if len(session_ids) != len(sessions):
            return
        if sorted(session_nos) != list(range(1, len(sessions) + 1)):
            self._error("$.sessions", "NON_CONTIGUOUS_SESSIONS",
                        "session_no values must be 1..N without gaps or duplicates.")

    def _validate_agents(self, agents: list[Any],
                         profile: dict[str, Any] | None = None) -> None:
        self._validate_unique_ids(agents, "agent_id", "$.agents")
        allowed_fields = set(BY_FIELD)
        if profile is not None:
            allowed_fields = (
                set(profile["core_persona_fields"]) |
                set(profile["domain_persona_fields"]) |
                set(profile["grouping_fields"])
            )
        for index, agent in enumerate(agents):
            path = f"$.agents[{index}]"
            if not isinstance(agent, dict):
                continue
            self._optional_string(agent, "source_persona_id", path)
            persona = agent.get("persona")
            if not isinstance(persona, dict):
                self._error(f"{path}.persona", "PERSONA_REQUIRED",
                            "A resolved persona object is required in v1.")
                continue
            for field_id, value in persona.items():
                if field_id not in allowed_fields:
                    self._error(f"{path}.persona.{field_id}", "UNKNOWN_PERSONA_FIELD",
                                "Persona field is not in the selected industry profile.")
                elif value is not None and value not in BY_FIELD[field_id]["values"]:
                    self._error(
                        f"{path}.persona.{field_id}", "INVALID_PERSONA_VALUE",
                        "Persona value is not one of the canonical enum values.",
                    )

    def _validate_shops(self, scenario: dict[str, Any],
                        shops: list[Any]) -> set[str]:
        ids = self._validate_unique_ids(shops, "shop_id", "$.shops")
        for index, shop in enumerate(shops):
            path = f"$.shops[{index}]"
            if not isinstance(shop, dict):
                continue
            self._match_owner_identity(scenario, shop, path)
            if not _is_nonempty_string(shop.get("public_profile")):
                self._error(f"{path}.public_profile", "PUBLIC_PROFILE_REQUIRED",
                            "A non-empty public_profile is required.")
            self._validate_tags(shop, "shop", path)
        return ids

    def _validate_posts(self, scenario: dict[str, Any], posts: list[Any],
                        shop_ids: set[str]) -> set[str]:
        ids = self._validate_unique_ids(posts, "post_id", "$.posts")
        for index, post in enumerate(posts):
            path = f"$.posts[{index}]"
            if not isinstance(post, dict):
                continue
            self._match_owner_identity(scenario, post, path)
            if post.get("shop_id") not in shop_ids:
                self._error(f"{path}.shop_id", "UNKNOWN_SHOP",
                            f"Shop {post.get('shop_id')!r} is not defined.")
            for field in ("title", "preview", "article_content"):
                if not _is_nonempty_string(post.get(field)):
                    self._error(f"{path}.{field}", "ARTICLE_FIELD_REQUIRED",
                                f"{field} must be a non-empty string.")
            self._validate_tags(post, "post", path)
        return ids

    def _validate_products(self, scenario: dict[str, Any],
                           products: list[Any], shop_ids: set[str]) -> None:
        ids = self._validate_unique_ids(products, "product_id", "$.products")
        positions: dict[str, set[int]] = {}
        for index, product in enumerate(products):
            path = f"$.products[{index}]"
            if not isinstance(product, dict):
                continue
            self._match_owner_identity(scenario, product, path)
            shop_id = product.get("shop_id")
            if shop_id not in shop_ids:
                self._error(f"{path}.shop_id", "UNKNOWN_SHOP",
                            f"Shop {shop_id!r} is not defined.")
            for field in ("product_name", "listed_price", "product_description"):
                if not _is_nonempty_string(product.get(field)):
                    self._error(f"{path}.{field}", "PRODUCT_FIELD_REQUIRED",
                                f"{field} must be a non-empty string.")
            position = product.get("position")
            if type(position) is not int or position < 1:
                self._error(f"{path}.position", "INVALID_POSITION",
                            "position must be a positive integer.")
            else:
                used = positions.setdefault(shop_id, set())
                if position in used:
                    self._error(f"{path}.position", "DUPLICATE_CATALOG_POSITION",
                                "Product position must be unique within one shop.")
                used.add(position)
            self._validate_tags(product, "product", path)
        if len(ids) != len(products):
            return

    def _match_owner_identity(self, scenario: dict[str, Any], item: dict[str, Any],
                              path: str, required: bool = True) -> None:
        for field in ("organization_id", "brand_id"):
            value = item.get(field)
            if value is None and not required:
                continue
            if not _is_nonempty_string(value):
                self._error(f"{path}.{field}", "OWNER_ID_REQUIRED",
                            f"{field} must be a non-empty string.")
            elif value != scenario.get(field):
                self._error(f"{path}.{field}", "OWNER_ID_MISMATCH",
                            f"{field} must match scenario.{field}.")

    def _validate_tags(self, owner: dict[str, Any], owner_type: str, path: str) -> None:
        assignments = owner.get("tags")
        if not isinstance(assignments, list):
            self._error(f"{path}.tags", "TAGS_REQUIRED",
                        "tags must be an explicit list; [] is allowed.")
            return
        family = OWNER_FAMILIES[owner_type]
        allowed_fields = OWNER_FIELDS[owner_type]
        allowed_stages = set(TAGS["families"][family]["stages"])
        owner_id = owner.get({"shop": "shop_id", "post": "post_id",
                              "product": "product_id"}[owner_type])
        seen: set[str] = set()
        for index, assignment in enumerate(assignments):
            item_path = f"{path}.tags[{index}]"
            if not isinstance(assignment, dict):
                self._error(item_path, "TAG_NOT_OBJECT",
                            "Each tag assignment must be an object.")
                continue
            if set(assignment) != {"tag_id", "source_ref", "visible_stages"}:
                self._error(item_path, "TAG_ASSIGNMENT_SHAPE",
                            "Tag assignments must contain exactly tag_id, source_ref "
                            "and visible_stages.")
                continue
            tag_id = assignment["tag_id"]
            if tag_id not in BY_TAG:
                self._error(f"{item_path}.tag_id", "UNKNOWN_TAG",
                            f"Tag {tag_id!r} is not in the canonical registry.")
                continue
            if tag_id in seen:
                self._error(f"{item_path}.tag_id", "DUPLICATE_TAG",
                            "A tag may be assigned only once to one object.")
            seen.add(tag_id)
            if BY_TAG[tag_id]["family"] != family:
                self._error(f"{item_path}.tag_id", "TAG_FAMILY_MISMATCH",
                            f"Tag must belong to the {family} family.")
            prefix = f"{owner_type}:{owner_id}:"
            source_ref = assignment["source_ref"]
            if not isinstance(source_ref, str) or not source_ref.startswith(prefix):
                self._error(f"{item_path}.source_ref", "TAG_SOURCE_MISMATCH",
                            "source_ref must point to a public field of this object.")
            else:
                source_field = source_ref[len(prefix):]
                if source_field not in allowed_fields:
                    self._error(f"{item_path}.source_ref", "TAG_SOURCE_FIELD",
                                "source_ref points to a field not allowed for this object.")
                elif not _is_nonempty_string(owner.get(source_field)):
                    self._error(f"{item_path}.source_ref", "TAG_SOURCE_EMPTY",
                                "The tag source field must contain public text.")
            stages = assignment["visible_stages"]
            if (not isinstance(stages, list) or not stages or
                    any(stage not in allowed_stages for stage in stages)):
                self._error(f"{item_path}.visible_stages", "TAG_VISIBILITY",
                            "visible_stages contains an invalid or missing stage.")
            if isinstance(stages, list):
                if "article_content" in str(assignment.get("source_ref", "")) and \
                        set(stages) & {"A1", "A2"}:
                    self._error(f"{item_path}.visible_stages", "EARLY_FULL_CONTENT",
                                "article_content cannot be visible before A3.")
                if "product_description" in str(assignment.get("source_ref", "")) and \
                        "B1" in stages:
                    self._error(f"{item_path}.visible_stages", "EARLY_PRODUCT_DETAILS",
                                "product_description cannot be visible at B1.")

    def _validate_customer_structure(self, scenario: dict[str, Any],
                                     agents: list[Any]) -> None:
        structure = scenario.get("customer_structure")
        if structure is None:
            return
        path = "$.customer_structure"
        if not isinstance(structure, dict):
            self._error(path, "INVALID_CUSTOMER_STRUCTURE",
                        "customer_structure must be an object.")
            return
        total = structure.get("total_agents")
        if type(total) is not int or total < 1:
            self._error(f"{path}.total_agents", "INVALID_TOTAL_AGENTS",
                        "total_agents must be a positive integer.")
        elif total != len(agents):
            self._error(f"{path}.total_agents", "AGENT_COUNT_MISMATCH",
                        "total_agents must equal the resolved agents list.")
        groups = structure.get("groups")
        if not isinstance(groups, list) or not groups:
            self._error(f"{path}.groups", "GROUPS_REQUIRED",
                        "At least one customer group is required.")
            return
        modes: set[str] = set()
        group_ids: set[str] = set()
        count_sum = 0
        percentage_sum = 0.0
        for index, group in enumerate(groups):
            group_path = f"{path}.groups[{index}]"
            if not isinstance(group, dict):
                self._error(group_path, "GROUP_NOT_OBJECT",
                            "Each group must be an object.")
                continue
            group_id = group.get("group_id")
            if not _is_nonempty_string(group_id):
                self._error(f"{group_path}.group_id", "GROUP_ID_REQUIRED",
                            "group_id must be a non-empty string.")
            elif group_id in group_ids:
                self._error(f"{group_path}.group_id", "DUPLICATE_GROUP_ID",
                            "group_id must be unique.")
            group_ids.add(group_id)
            agent_ids = group.get("agent_ids")
            if (not isinstance(agent_ids, list) or
                    len(set(agent_ids)) != len(agent_ids)):
                self._error(f"{group_path}.agent_ids", "INVALID_GROUP_MEMBERS",
                            "agent_ids must be a list without duplicates.")
            else:
                known_agents = {
                    item.get("agent_id") for item in agents
                    if isinstance(item, dict)
                }
                if any(agent_id not in known_agents for agent_id in agent_ids):
                    self._error(f"{group_path}.agent_ids", "UNKNOWN_GROUP_AGENT",
                                "Every group agent_id must exist in agents.")
            has_count = "count" in group
            has_percentage = "percentage" in group
            if has_count == has_percentage:
                self._error(group_path, "GROUP_ALLOCATION_MODE",
                            "Each group must provide exactly one of count or percentage.")
                continue
            mode = "count" if has_count else "percentage"
            modes.add(mode)
            value = group[mode]
            if mode == "count":
                if type(value) is not int or value < 0:
                    self._error(f"{group_path}.count", "INVALID_GROUP_COUNT",
                                "count must be an integer >= 0.")
                else:
                    count_sum += value
            else:
                if type(value) not in (int, float) or not 0 <= value <= 100:
                    self._error(f"{group_path}.percentage", "INVALID_GROUP_PERCENTAGE",
                                "percentage must be between 0 and 100.")
                else:
                    percentage_sum += float(value)
        if len(modes) > 1:
            self._error(path, "MIXED_ALLOCATION_MODES",
                        "Use count for every group or percentage for every group in v1.")
        elif modes == {"count"} and count_sum != len(agents):
            self._error(path, "GROUP_COUNT_SUM",
                        "Group counts must equal the resolved agent count.")
        elif modes == {"percentage"} and abs(percentage_sum - 100) > 1e-6:
            self._error(path, "GROUP_PERCENTAGE_SUM",
                        "Group percentages must sum to 100.")
        if modes:
            expected_counts = _rounded_counts(groups, len(agents))
            all_members: list[str] = []
            for index, (group, expected) in enumerate(zip(groups, expected_counts)):
                members = group.get("agent_ids", [])
                if len(members) != expected:
                    self._error(
                        f"{path}.groups[{index}].agent_ids",
                        "GROUP_ALLOCATION_MISMATCH",
                        f"This group must contain {expected} agent(s) after "
                        "deterministic allocation.",
                    )
                all_members.extend(members)
            known_agents = {
                item.get("agent_id") for item in agents
                if isinstance(item, dict)
            }
            if len(all_members) != len(set(all_members)) or set(all_members) != known_agents:
                self._error(
                    f"{path}.groups",
                    "GROUP_PARTITION",
                    "Groups must partition all resolved agents exactly once.",
                )

    def _validate_relationships(self, scenario: dict[str, Any],
                                agents: list[Any]) -> None:
        agent_ids = [
            agent.get("agent_id") for agent in agents
            if isinstance(agent, dict)
        ]
        initialization = scenario.get("relationship_initialization")
        if initialization is not None:
            for issue in validate_initialization(initialization, agent_ids):
                self._error(issue.path, issue.code, issue.message)
        assignments = scenario.get("relationship_assignments")
        if assignments is not None:
            for issue in validate_assignments(
                assignments,
                agent_ids,
                organization_id=scenario.get("organization_id"),
                brand_id=scenario.get("brand_id"),
            ):
                self._error(issue.path, issue.code, issue.message)
        if initialization is not None or assignments is not None:
            try:
                canonical = materialize_relationships(scenario)
            except ValueError:
                # Detailed errors have already been added above. This guard
                # prevents a malformed assignment from escaping validation.
                pass
            else:
                if assignments is not None and assignments != canonical:
                    self._error(
                        "$.relationship_assignments",
                        "ASSIGNMENT_DRIFT",
                        "Supplied assignments do not match deterministic materialization.",
                    )

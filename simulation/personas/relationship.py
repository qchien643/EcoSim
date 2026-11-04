"""Relationship context selection and deterministic post-event transitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .assignment import (
    RELATIONSHIP_FIELDS,
    RELATIONSHIP_VALUES,
    default_relationship,
    validate_relationship_state,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads(
    (ROOT / "data/contracts/relationship-context-policy.v1.json")
    .read_text(encoding="utf-8")
)

CONTEXT_FIELDS = POLICY["context_fields"]
BRAND_HISTORY_FIELDS = POLICY["brand_history_fields"]


def fields_for_stage(stage: str) -> list[str]:
    return list(CONTEXT_FIELDS.get(stage, []))


def history_fields_for_stage(stage: str) -> list[str]:
    return list(BRAND_HISTORY_FIELDS.get(stage, []))


def project_relationship(state: dict[str, Any] | None, stage: str) -> dict[str, str]:
    source = dict(default_relationship() if state is None else state)
    if validate_relationship_state(source):
        raise ValueError("Invalid relationship state")
    return {field: source[field] for field in fields_for_stage(stage)}


def project_brand_history(history: dict[str, Any], stage: str) -> dict[str, int]:
    result = {}
    for field in history_fields_for_stage(stage):
        value = history.get(field, 0)
        if type(value) is not int or value < 0:
            raise ValueError(f"Invalid brand history value: {field}")
        result[field] = value
    return result


def transition_relationship(
    current: dict[str, str],
    event: dict[str, Any],
) -> dict[str, str]:
    """Apply only explicit evidence; feelings do not silently become attitude."""
    if validate_relationship_state(current):
        raise ValueError("Invalid current relationship state")
    next_state = dict(current)
    stage = event.get("stage")
    action = event.get("action")
    brand_identity_visible = bool(event.get("brand_identity_visible"))

    if stage == "A3" and event.get("status", "resolved") == "resolved" and \
            brand_identity_visible:
        next_state["awareness"] = "aware"
        if next_state["familiarity"] == "none":
            next_state["familiarity"] = "low"

    if stage == "A5" and action in {"visit", "visit_again"}:
        next_state["awareness"] = "aware"
        if action == "visit_again" or next_state["familiarity"] == "low":
            next_state["familiarity"] = "established"
        elif next_state["familiarity"] == "none":
            next_state["familiarity"] = "low"

    if stage == "B3" and action in {"buy", "buy_again"}:
        next_state["awareness"] = "aware"
        next_state["familiarity"] = "established"
        next_state["purchase_history"] = "has_purchased"

    if validate_relationship_state(next_state):
        raise ValueError("Relationship transition produced an invalid state")
    return next_state


def validate_policy() -> None:
    expected_stages = {"A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3"}
    if set(CONTEXT_FIELDS) != expected_stages or \
            set(BRAND_HISTORY_FIELDS) != expected_stages:
        raise ValueError("Relationship policy must cover every decision stage")
    for fields in CONTEXT_FIELDS.values():
        if len(fields) != len(set(fields)) or any(
            field not in RELATIONSHIP_FIELDS for field in fields
        ):
            raise ValueError("Invalid relationship context field list")
    for fields in BRAND_HISTORY_FIELDS.values():
        if len(fields) != len(set(fields)):
            raise ValueError("Duplicate brand history field")
    for transition in POLICY["transitions"]:
        if not transition["updates"]:
            raise ValueError("Transition must declare an explicit update")

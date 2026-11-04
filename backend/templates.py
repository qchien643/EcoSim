"""Versioned, file-backed examples. Instantiation never starts a simulation."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .contracts import issues_for
from .store import BackendConflictError, BackendNotFoundError, BackendValidationError, hash_json, now

ROOT = Path(__file__).resolve().parents[1] / "data/scenario_templates"


def catalog():
    # ponytail: a small bundled catalog; add a database only for user-managed templates.
    result = []
    for path in sorted(ROOT.glob("*/*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        errors = issues_for(item, "ScenarioTemplate")
        if errors:
            raise BackendValidationError(errors)
        result.append(item)
    if len({t["template_id"] for t in result}) != len(result):
        raise ValueError("Duplicate template ID")
    return result


def get_template(template_id):
    # Never turn a user-supplied identifier into a filesystem path.
    for item in catalog():
        if item["template_id"] == template_id:
            return item
    raise BackendNotFoundError("Unknown scenario template")


def summary(template):
    setup = template["setup"]
    return {**{k: template[k] for k in ("template_id", "name", "description")},
            "industry_id": setup["industry_id"], "agent_count": setup["agent_count"],
            **{f"{key[:-1]}_count": len(setup[key])
               for key in ("sessions", "shops", "posts", "products")}}


def fresh_setup(template, name):
    setup = deepcopy(template["setup"])
    setup["name"] = name
    mapping = {}
    owners = [("organization", setup["business"]), ("brand", setup["business"])]
    owners += [(kind, obj) for kind, key in (
        ("shop", "shops"), ("post", "posts"), ("product", "products"), ("group", "relationship_groups")
    ) for obj in setup[key]]
    for kind, obj in owners:
        field = f"{kind}_id"
        old = obj[field]
        mapping[kind, old] = f"{kind}_{uuid4().hex[:12]}"
        obj[field] = mapping[kind, old]
    for obj in setup["posts"] + setup["products"]:
        obj["shop_id"] = mapping["shop", obj["shop_id"]]
    for session in setup["sessions"]:
        for post in session["posts"]:
            post["post_id"] = mapping["post", post["post_id"]]
    for obj in [setup["business"], *setup["shops"], *setup["posts"], *setup["products"]]:
        for tag in obj["tags"]:
            kind, identity, field = tag["source_ref"].split(":", 2)
            tag["source_ref"] = f"{kind}:{mapping[kind, identity]}:{field}"
    return setup


def instantiate(store, template_id, payload, key):
    errors = issues_for(payload, "TemplateInstantiationInput")
    if errors:
        raise BackendValidationError(errors)
    if not isinstance(key, str) or not 1 <= len(key.strip()) <= 128:
        raise BackendValidationError([{
            "path": "Idempotency-Key", "code": "REQUIRED", "message": "A nonempty command key is required."
        }])
    key = key.strip()
    request_hash = hash_json({"template_id": template_id, "payload": payload})
    with store.transaction() as db:
        previous = db.execute(
            "SELECT * FROM idempotency_keys WHERE idempotency_key=?", (key,)
        ).fetchone()
        if previous:
            if previous["operation"] != "instantiate_template" or previous["request_hash"] != request_hash:
                raise BackendConflictError("Idempotency key was used for another request")
            scenario = store.get_scenario(previous["resource_id"])
            return {"campaign_id": scenario["campaign_id"], "scenario_id": scenario["scenario_id"]}
        template = get_template(template_id)
        setup = fresh_setup(template, payload["scenario_name"])
        campaign = store.create_campaign(payload["campaign"])
        scenario = store.create_scenario(campaign["campaign_id"], setup)
        report = store.validate_scenario(scenario["scenario_id"])
        if not report["valid"]:
            raise BackendValidationError(report["issues"])
        db.execute("INSERT INTO idempotency_keys VALUES (?, ?, ?, ?, ?)",
                   (key, "instantiate_template", request_hash, scenario["scenario_id"], now()))
        return {"campaign_id": campaign["campaign_id"], "scenario_id": scenario["scenario_id"]}

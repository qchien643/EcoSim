"""Build stage-scoped, durable contexts from the frozen run and committed events."""

from .renderer import (
    BY_FIELD, BY_TAG, CONTRACT, FACTS, MAPPING, SCOPE, TAGS, UPSTREAM, render, require,
)
from ..personas.assignment import default_relationship
from ..personas.relationship import (
    history_fields_for_stage,
    project_brand_history,
    project_relationship,
)


def one(items, field, value):
    matches = [item for item in items if item.get(field) == value]
    require(len(matches) == 1, f"Missing or duplicate snapshot record: {field}")
    return matches[0]


def renderer_state(state):
    """Project storage fields into the renderer's strict state contract."""
    result = {key: state[key] for key in SCOPE | {"stage", "status", "encounter_no"}}
    if state["status"] == "resolved":
        if state["stage"] in {"A1", "B1"}:
            result.update(score=state["score"], action=state["action"])
        elif state["stage"] in {"A4", "A5", "B3"}:
            result["action"] = state["action"]
        else:
            result["tags"] = [
                {"tag_id": tag["tag_id"], "score": tag["normalized_score"]}
                for tag in state["tags"]
            ]
    return result


def _object_by_event(snapshot, event):
    collection = snapshot["posts"] if event["object_type"] == "article" \
        else snapshot["products"]
    key = "post_id" if event["object_type"] == "article" else "product_id"
    return next((item for item in collection if item.get(key) == event["object_id"]), None)


def _brand_history(snapshot, events, brand_id):
    result = {
        "article_exposure_count": 0,
        "article_read_count": 0,
        "shop_visit_count": 0,
        "product_exposure_count": 0,
        "brand_purchase_count": 0,
    }
    for event in events:
        obj = _object_by_event(snapshot, event)
        if not obj or obj.get("brand_id") != brand_id:
            continue
        stage = event["stage"]
        if stage == "A1":
            result["article_exposure_count"] += 1
        elif stage == "A3" and event["status"] == "resolved":
            result["article_read_count"] += 1
        elif stage == "A5" and event["status"] == "resolved" and \
                event["action"] in {"visit", "visit_again"}:
            result["shop_visit_count"] += 1
        elif stage == "B1":
            result["product_exposure_count"] += 1
        elif stage == "B3" and event["status"] == "resolved" and \
                event["action"] in {"buy", "buy_again"}:
            result["brand_purchase_count"] += 1
    return result


def object_memory(store, events, stages):
    """Latest state per allowed stage, including empty or unresolved outcomes."""
    latest = {event["stage"]: event for event in events if event["stage"] in stages}
    return [
        renderer_state(store.event_state(latest[stage]["event_id"]))
        for stage in stages if stage in latest
    ]


class ContextService:
    def __init__(self, store):
        self.store = store

    def _tags(self, owner, owner_type, owner_id, stage, registry=None):
        """Source refs must resolve to public fields of this exact snapshot owner."""
        TAGS = registry or globals()["TAGS"]
        BY_TAG = {tag["id"]: tag for tag in TAGS["tags"]}
        assignments = owner.get("tags")
        require(isinstance(assignments, list), "Snapshot must declare tags (empty is allowed)")
        family = {"shop": "enterprise", "organization": "enterprise", "brand": "enterprise",
                  "post": "article", "product": "product"}[owner_type]
        fields = {"shop": {"public_profile"}, "post": {"preview", "article_content"},
                  "organization": {"organization_description"}, "brand": {"brand_description"},
                  "product": {"product_name", "listed_price", "product_description"}}[owner_type]
        visible, seen = [], set()
        for item in assignments:
            require(isinstance(item, dict) and
                    set(item) == {"tag_id", "source_ref", "visible_stages"}, "Invalid tag assignment")
            tag_id = item["tag_id"]
            require(isinstance(tag_id, str) and tag_id in BY_TAG and tag_id not in seen,
                    "Unknown or duplicate input tag")
            require(BY_TAG[tag_id]["family"] == family, "Tag assigned to wrong owner family")
            seen.add(tag_id)
            require(isinstance(item["source_ref"], str), "Invalid tag evidence")
            prefix = f"{owner_type}:{owner_id}:"
            require(item["source_ref"].startswith(prefix), "Tag evidence belongs to another owner")
            field = item["source_ref"][len(prefix):]
            require(field in fields and isinstance(owner.get(field), str) and owner[field].strip(),
                    "Tag source must resolve to a nonempty public field")
            stages = item["visible_stages"]
            require(isinstance(stages, list) and stages and
                    all(s in TAGS["families"][family]["stages"] for s in stages),
                    "Invalid tag visibility")
            require(field != "article_content" or not set(stages) & {"A1", "A2"},
                    "Full-content evidence cannot be exposed before reading")
            require(field != "product_description" or "B1" not in stages,
                    "Product details cannot be exposed during attention")
            # Renderer interprets business visibility at A4 using A3 visibility.
            if (stage != "A4" and stage in stages) or (
                    stage == "A4" and "A3" in stages and "A4" in stages):
                visible.append(item)
        return visible

    def build(self, *, run_id, session_id, agent_id, object_type, object_id,
              encounter_no, stage, parent_event_id=None):
        bundle = self.store.run_bundle(run_id)
        CONTRACT, TAGS, MAPPING = bundle["renderer"], bundle["tag_registry"], bundle["persona_mapping"]
        require(stage in CONTRACT["stage_rendering"], "Unknown context stage")
        require(object_type == ("article" if stage.startswith("A") else "product"),
                "Stage/object mismatch")
        require(type(encounter_no) is int and encounter_no >= 1, "Invalid encounter")
        scope = dict(run_id=run_id, agent_id=agent_id, object_type=object_type, object_id=object_id)
        key = self.store.stage_key(run_id, session_id, agent_id, object_type,
                                   object_id, encounter_no, stage)
        cached = self.store.context_snapshot(key)
        if cached is not None:
            require(cached["rendered"]["renderer_version"] == CONTRACT["version"],
                    "Context version changed; start a new run instead of mixing versions")
            require(cached["input"]["scope"] == scope and
                    cached["parent_event_id"] == parent_event_id and
                    cached["input"]["stage"] == stage and
                    cached["input"]["encounter_no"] == encounter_no,
                    "Context identity conflict")
            return cached

        snapshot = self.store.run_snapshot(run_id)
        agent = one(snapshot["agents"], "agent_id", agent_id)
        session = one(snapshot["sessions"], "session_id", session_id)
        require("active_agents" not in session or agent_id in session["active_agents"],
                "Agent is not active in this session")
        object_key = "post_id" if object_type == "article" else "product_id"
        objects = snapshot["posts"] if object_type == "article" else snapshot["products"]
        obj = one(objects, object_key, object_id)
        shop = one(snapshot["shops"], "shop_id", obj.get("shop_id"))
        brand_id = obj.get("brand_id")
        require(brand_id == snapshot["brand_id"], "Object belongs to another brand")
        if object_type == "article":
            require(any(p["post_id"] == object_id for p in session.get("posts", [])),
                    "Article is not scheduled in this session")

        attention = "A1" if object_type == "article" else "B1"
        attention_key = self.store.stage_key(run_id, session_id, agent_id, object_type,
                                             object_id, encounter_no, attention)
        attention_context = self.store.context_snapshot(attention_key)
        if stage != attention:
            require(attention_context is not None, "Missing current attention snapshot")
        watermark = (attention_context["watermark"] if attention_context else
                     self.store.history_watermark(run_id))
        events = self.store.history_before(run_id, agent_id, watermark)
        same_object = [e for e in events if e["object_type"] == object_type and
                       e["object_id"] == object_id]
        previous = [e for e in same_object if e["stage"] == stage]
        parent = self.store.event(parent_event_id) if parent_event_id else None
        if parent_event_id:
            require(parent is not None and parent["run_id"] == run_id and
                    parent["agent_id"] == agent_id and parent["session_id"] == session_id and
                    parent["status"] == "resolved", "Invalid parent event scope/status")
        expected_parent = {"A1R": "A1", "A2": "A1", "A3": "A2", "A4": "A3",
                           "A5": "A4", "B1R": "B1", "B2": "B1", "B3": "B2"}
        if stage in expected_parent:
            require(parent is not None and parent["stage"] == expected_parent[stage] and
                    parent["object_type"] == object_type and parent["object_id"] == object_id and
                    parent["encounter_no"] == encounter_no, "Wrong current upstream event")
            if stage in {"A1R", "B1R", "A2", "B2"}:
                actions = {"skip"} if stage.endswith("R") else {"attend", "attend_again"}
                require(parent["action"] in actions, "Stage incompatible with attention action")
        elif stage == "B1":
            require(parent is not None and parent["stage"] == "A5" and
                    parent["action"] in {"visit", "visit_again"}, "Product requires a shop visit")
            origin = one(snapshot["posts"], "post_id", parent["object_id"])
            require(origin["shop_id"] == obj["shop_id"], "Product belongs to another shop")
        else:
            require(parent is None, "Unexpected parent at article attention")

        data = {"stage": stage, "scope": scope, "encounter_no": encounter_no}
        if previous and stage not in {"A1", "B1"}:
            data["previous_same_stage_state"] = renderer_state(
                self.store.event_state(previous[-1]["event_id"]))
        history = {}
        if stage in {"A1", "B1"}:
            history = {"attention_count": sum(e["stage"] == stage and
                       e["action"] in {"attend", "attend_again"} for e in same_object)}
            if previous and previous[-1]["action"] == "skip":
                reasons = [e for e in same_object if e["stage"] == stage + "R" and
                           e["encounter_no"] == previous[-1]["encounter_no"]]
                if reasons:
                    data["previous_attention_reason"] = renderer_state(
                        self.store.event_state(reasons[-1]["event_id"]))
            summary = {
                "prior_exposure_count": sum(e["stage"] == stage for e in same_object),
                "states": object_memory(
                    self.store, same_object,
                    ("A1", "A3", "A4", "A5") if stage == "A1" else ("B1", "B2", "B3")),
            }
            if stage == "A1":
                summary["prior_read_count"] = sum(
                    e["stage"] == "A3" and e["status"] == "resolved" for e in same_object)
                data["article_memory_summary"] = summary
            else:
                summary["prior_purchase_count"] = sum(
                    e["stage"] == "B3" and e["action"] in {"buy", "buy_again"}
                    for e in same_object)
                data["product_memory_summary"] = summary
        elif stage == "B2":
            data["product_memory_summary"] = {
                "prior_purchase_count": sum(
                    e["stage"] == "B3" and e["action"] in {"buy", "buy_again"}
                    for e in same_object),
                "states": object_memory(self.store, same_object, ("B3",)),
            }
        elif stage == "A4":
            reaction = None
            for event in same_object:
                if event["stage"] == "A4" and event["status"] == "resolved":
                    if event["action"] in {"like", "dislike"}:
                        reaction = event["action"]
                    elif event["action"] == "remove_reaction":
                        reaction = None
            history = {"current_reaction": reaction}
        elif stage == "A5":
            post_ids = {p["post_id"] for p in snapshot["posts"] if p["shop_id"] == obj["shop_id"]}
            history = {"shop_visit_count": sum(
                e["stage"] == "A5" and e["status"] == "resolved" and
                e["object_type"] == "article" and e["object_id"] in post_ids and
                e["action"] in {"visit", "visit_again"} for e in events)}
        elif stage == "B3":
            history = {"purchase_count": sum(e["stage"] == "B3" and
                       e["action"] in {"buy", "buy_again"} for e in same_object)}

        if stage.endswith("R"):
            data["attention_snapshot"] = {
                "input": attention_context["input"],
                "decision": renderer_state(self.store.event_state(parent_event_id)),
            }
        else:
            data["history"] = history
            relationship = self.store.relationship(
                run_id, agent_id, snapshot["organization_id"], brand_id
            )
            relationship_state = relationship["state"] if relationship else default_relationship()
            if stage in {"A1", "A2", "B1", "B2"}:
                data["relationship_state"] = project_relationship(relationship_state, stage)
            business_tags = self._tags(shop, "shop", obj["shop_id"], stage, TAGS)
            business = snapshot["business"]
            evidence = {}
            for owner_type in ("organization", "brand"):
                owner = {**business, "tags": [
                    t for t in business["tags"] if t["source_ref"].startswith(owner_type + ":")
                ]}
                business_tags.extend(self._tags(
                    owner, owner_type, business[owner_type + "_id"], stage, TAGS
                ))
            for item in business_tags:
                evidence.setdefault(item["tag_id"], []).append(item["source_ref"])
            business_tags = list({t["tag_id"]: t for t in business_tags}.values())
            object_tags = self._tags(obj, "post" if object_type == "article" else "product",
                                     object_id, stage, TAGS)
            if stage in {"A4", "B3"}:
                business_tags, object_tags = [], []
            elif stage == "A3":
                object_tags = []
            data["visible_tags"] = business_tags + ([] if stage in {"A4", "A5"} else object_tags)
            data["facts"] = {field: obj[field] for field in FACTS[stage] if field in obj}
            if stage == "A3":
                require("article_content" in data["facts"], "Missing readable article content")
            if stage in {"B1", "B2", "B3"}:
                require({"product_name", "listed_price"} <= data["facts"].keys(),
                        "Missing public product name/price")
            if MAPPING["stage_policy"][stage]["mode"] == "select":
                persona = agent.get("persona")
                require(isinstance(persona, dict), "Missing run persona snapshot")
                candidates = list(MAPPING["stage_policy"][stage]["base_fields"])
                rules = {r["tag_id"]: r["fields"] for r in MAPPING["rules"]}
                for tag_id in sorted(t["tag_id"] for t in data["visible_tags"]):
                    candidates.extend(rules[tag_id])
                data["persona"] = {f: persona[f] for f in dict.fromkeys(candidates)
                                   if persona.get(f) is not None}
            if stage in UPSTREAM:
                upstream = parent
                if stage == "A5":
                    upstream = self.store.event(parent["parent_event_id"])
                    require(upstream is not None and upstream["stage"] == "A3" and
                            all(upstream[k] == parent[k] for k in
                                ("run_id", "session_id", "agent_id", "object_type",
                                 "object_id", "encounter_no")), "Missing current A3 feelings")
                data["current_state"] = renderer_state(
                    self.store.event_state(upstream["event_id"]))

        rendered = render(data, bundle)
        result = {
            "input": data, "rendered": rendered, "history": history,
            "watermark": watermark, "parent_event_id": parent_event_id,
            "mapping_version": MAPPING["version"], "registry_version": TAGS["version"],
            "business_evidence": evidence if not stage.endswith("R") else {},
        }
        self.store.save_context(key, run_id, result)
        return result

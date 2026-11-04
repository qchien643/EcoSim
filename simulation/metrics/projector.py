"""Deterministic, rebuildable session metrics; never calls a model."""

from collections import Counter
import json

from ..decision.policy import POLICY, TAGS

CALCULATION_VERSION = "metrics-v1"
STAGES = ("A1", "A1R", "A2", "A3", "A4", "A5", "B1", "B1R", "B2", "B3")
STATUSES = ("resolved", "empty_result", "unresolved")
ACTION_METRICS = {
    "posts_attended": ("A1", {"attend", "attend_again"}),
    "posts_skipped": ("A1", {"skip"}),
    "likes_added": ("A4", {"like"}),
    "dislikes_added": ("A4", {"dislike"}),
    "no_reaction": ("A4", {"no_reaction"}),
    "reactions_kept": ("A4", {"keep_current"}),
    "reactions_removed": ("A4", {"remove_reaction"}),
    "no_new_reaction": ("A4", {"no_new_reaction"}),
    "shop_visits": ("A5", {"visit", "visit_again"}),
    "shop_not_visits": ("A5", {"not_visit", "not_visit_again"}),
    "products_attended": ("B1", {"attend", "attend_again"}),
    "products_skipped": ("B1", {"skip"}),
    "buys": ("B3", {"buy", "buy_again"}),
    "not_buys": ("B3", {"not_buy", "not_buy_again"}),
}
RATES = {
    "post_attention_rate": ("posts_attended", "stage.A1.resolved"),
    "read_rate": ("posts_read", "posts_attended"),
    "shop_visit_rate": ("shop_visits", "stage.A5.resolved"),
    "product_attention_rate": ("products_attended", "stage.B1.resolved"),
    "purchase_rate": ("buys", "stage.B3.resolved"),
}
TAG_METRICS = {
    f"tag.{stage}.{tag_id}.selected"
    for stage, config in POLICY["tag_selection"].items()
    for tag_id, tag in TAGS.items() if tag["family"] == config["family"]
}
COUNTS = (
    set(ACTION_METRICS) | TAG_METRICS |
    {f"stage.{stage}.{status}" for stage in STAGES for status in STATUSES} |
    {"posts_exposed", "products_exposed", "posts_read", "stage_events",
     "empty_result", "unresolved", "resolved_source.jev",
     "resolved_source.llm_fallback", "resolved_source.unknown"}
)
GAUGES = {"current_likes", "current_dislikes"}

def _scope_events(snapshot, events, scope_type, scope_id):
    if scope_type == "run":
        return list(events)
    posts = {item["post_id"]: item for item in snapshot["posts"]}
    products = {item["product_id"]: item for item in snapshot["products"]}
    if scope_type == "article":
        return [event for event in events
                if event["object_type"] == "article"
                and event["object_id"] == scope_id]
    if scope_type == "product":
        return [event for event in events
                if event["object_type"] == "product"
                and event["object_id"] == scope_id]
    if scope_type == "shop":
        return [event for event in events if (
            event["object_type"] == "article"
            and event["stage"] == "A5"
            and posts.get(event["object_id"], {}).get("shop_id") == scope_id
        ) or (
            event["object_type"] == "product"
            and products.get(event["object_id"], {}).get("shop_id") == scope_id
        )]
    raise ValueError(f"Unknown metric scope: {scope_type}")

def metric_names(bundle=None):
    if bundle is None:
        return COUNTS | GAUGES | set(RATES)
    tags = bundle["tag_registry"]["tags"]
    selected = {
        f"tag.{stage}.{tag['id']}.selected"
        for stage, config in bundle["policy"]["tag_selection"].items()
        for tag in tags if tag["family"] == config["family"]
    }
    return (COUNTS - TAG_METRICS) | selected | GAUGES | set(RATES)


def _scope_metric_names(scope_type, bundle=None):
    all_names = metric_names(bundle)
    if scope_type == "run":
        return all_names
    if scope_type == "article":
        stages = {"A1", "A1R", "A2", "A3", "A4", "A5"}
        return {name for name in all_names if (
            name in {"posts_exposed", "posts_read", "current_likes",
                     "current_dislikes", "post_attention_rate", "read_rate",
                     "shop_visit_rate"}
            or name in ACTION_METRICS
            and ACTION_METRICS[name][0] in stages
            or name.startswith("stage.") and name.split(".")[1] in stages
            or name.startswith("tag.") and name.split(".")[1] in stages
        )}
    if scope_type == "product":
        stages = {"B1", "B1R", "B2", "B3"}
        return {name for name in all_names if (
            name in {"products_exposed", "product_attention_rate",
                     "purchase_rate"}
            or name in ACTION_METRICS
            and ACTION_METRICS[name][0] in stages
            or name.startswith("stage.") and name.split(".")[1] in stages
            or name.startswith("tag.") and name.split(".")[1] in stages
        )}
    if scope_type == "shop":
        return _scope_metric_names("product", bundle) | {
            "shop_visits", "shop_not_visits", "shop_visit_rate",
            *(f"stage.A5.{status}" for status in STATUSES),
        }
    raise ValueError(f"Unknown metric scope: {scope_type}")


def summarize(events):
    counts = Counter({name: 0 for name in COUNTS})
    reactions = {}
    for event in events:
        stage, status, action = event["stage"], event["status"], event["action"]
        counts["stage_events"] += 1
        counts[f"stage.{stage}.{status}"] += 1
        if stage == "A1":
            counts["posts_exposed"] += 1
        elif stage == "B1":
            counts["products_exposed"] += 1
        if status != "resolved":
            counts[status] += 1
            continue
        response = json.loads(event["model_response_json"] or "{}")
        source = response.get("source")
        if source not in {"jev", "llm_fallback"}:
            source = "unknown"
        counts[f"resolved_source.{source}"] += 1
        if stage == "A3":
            counts["posts_read"] += 1
        for name, (expected_stage, actions) in ACTION_METRICS.items():
            if stage == expected_stage and action in actions:
                counts[name] += 1
        for tag in event["tags"]:
            if tag["selected"]:
                counts[f"tag.{stage}.{tag['tag_id']}.selected"] += 1
        if stage == "A4":
            key = (event["agent_id"], event["object_id"])
            if action in {"like", "dislike"}:
                reactions[key] = action
            elif action == "remove_reaction":
                reactions.pop(key, None)
    counts["current_likes"] = sum(value == "like" for value in reactions.values())
    counts["current_dislikes"] = sum(value == "dislike" for value in reactions.values())
    return counts


class MetricsProjector:
    def __init__(self, store):
        self.store = store

    def project_session(self, run_id, session_id, *, complete=False):
        """complete=True is called only by the coordinator after its session loop."""
        session = self.store.session(session_id)
        if session is None or session["run_id"] != run_id:
            raise ValueError("Unknown run/session")
        allowed = {"running", "completed"} if complete else {"completed"}
        if session["status"] not in allowed:
            raise ValueError("Only a finished session can be projected")
        if any(s["session_no"] < session["session_no"] and s["status"] != "completed"
               for s in self.store.sessions(run_id)):
            raise ValueError("Previous sessions must be completed first")
        # ponytail: replay the run prefix for v1; use incremental aggregation if
        # measured run sizes make prefix replay expensive, preserving rebuild.
        snapshot = self.store.run_snapshot(run_id)
        bundle = self.store.run_bundle(run_id)
        events = self.store.events_until_session(run_id, session["session_no"])
        current_events = [e for e in events if e["session_id"] == session_id]
        run_current = summarize(current_events)
        snapshots = []
        scopes = [("run", run_id)]
        scopes += [("article", item["post_id"]) for item in snapshot["posts"]]
        scopes += [("shop", item["shop_id"]) for item in snapshot["shops"]]
        scopes += [("product", item["product_id"]) for item in snapshot["products"]]
        for scope_type, scope_id in scopes:
            current_events_for_scope = _scope_events(
                snapshot, current_events, scope_type, scope_id
            )
            cumulative_events_for_scope = _scope_events(
                snapshot, events, scope_type, scope_id
            )
            current = summarize(current_events_for_scope)
            cumulative = summarize(cumulative_events_for_scope)
            for name in sorted(_scope_metric_names(scope_type, bundle)):
                denominator = cumulative_denominator = None
                numerator, cumulative_numerator = current[name], cumulative[name]
                if name in GAUGES:
                    numerator = cumulative_numerator
                if name in RATES:
                    numerator_key, denominator_key = RATES[name]
                    numerator, denominator = current[numerator_key], current[denominator_key]
                    cumulative_numerator = cumulative[numerator_key]
                    cumulative_denominator = cumulative[denominator_key]
                snapshots.append({
                    "run_id": run_id, "session_id": session_id,
                    "session_no": session["session_no"],
                    "scope_type": scope_type, "scope_id": scope_id,
                    "metric_name": name,
                    "numerator": numerator, "denominator": denominator,
                    "session_value": (numerator if denominator is None else
                                      numerator / denominator if denominator else None),
                    "cumulative_numerator": cumulative_numerator,
                    "cumulative_denominator": cumulative_denominator,
                    "cumulative_value": (
                        cumulative_numerator if cumulative_denominator is None else
                        cumulative_numerator / cumulative_denominator
                        if cumulative_denominator else None),
                    "calculation_version": CALCULATION_VERSION,
                })
        self.store.save_session_projection(run_id, session_id, snapshots, {
            "agents_processed": self.store.completed_agents(run_id, session_id),
            "posts_attended": run_current["posts_attended"],
            "products_bought": run_current["buys"],
            "unresolved_stages": run_current["unresolved"],
        }, complete=complete)
        return snapshots

    def rebuild(self, run_id):
        if self.store.run_status(run_id) is None:
            raise ValueError("Unknown run")
        for session in self.store.sessions(run_id):
            if session["status"] != "completed":
                break
            self.project_session(run_id, session["session_id"])

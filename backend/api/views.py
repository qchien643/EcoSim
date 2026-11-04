"""Public read models; no provider calls or simulation state changes."""

import base64
import hashlib
import json
from contextlib import contextmanager

from backend.contracts import SPEC
from backend.store import BackendNotFoundError
from simulation.metrics.projector import (
    CALCULATION_VERSION, GAUGES, RATES, _scope_metric_names, metric_names,
)


def public(schema, row):
    return {key: row[key] for key in SPEC["components"]["schemas"][schema]["properties"]
            if key in row}


def campaign(row):
    return {"campaign_id": row["campaign_id"], "revision": row["revision"],
            "campaign": public("CampaignInput", row)}


def industry(row):
    profile = row["bundle"]["profile"]
    return public("Industry", {**row, "name": profile.get("name") or
                              profile.get("display_name") or row["industry_id"]})


def bundle(row):
    data = row["bundle"]
    # ponytail: MVP has no industry-specific object extensions; add versioned
    # object schemas to the bundle before allowing those fields.
    return {
        "industry": industry(row), "persona_schema": data["persona_schema"],
        "tag_registry": data["tag_registry"], "persona_mapping": data["persona_mapping"],
        "object_schemas": data.get("object_schemas", {
            key: {"type": "object", "additionalProperties": False}
            for key in ("shop", "post", "product")
        }),
        "context_contract": data["renderer"], "policy": data["policy"],
    }


def participant(row):
    return {"agent_id": row["agent_id"], "ordinal": row["ordinal"],
            "persona": public("Persona", row), "group_id": row["group_id"],
            "initial_relationship": row["initial_relationship"]}


def cursor(scope, key):
    binding = hashlib.sha256(scope.encode()).hexdigest()[:24]
    return base64.urlsafe_b64encode(json.dumps([binding, key]).encode()).decode().rstrip("=")


def read_cursor(value, scope):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 512:
            raise ValueError
        decoded = json.loads(base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True))
        binding = hashlib.sha256(scope.encode()).hexdigest()[:24]
        if not isinstance(decoded, list) or len(decoded) != 2 or decoded[0] != binding:
            raise ValueError
        return decoded[1]
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError("Invalid cursor for this resource/filter") from error


def page(items, *, scope, key, limit, after):
    if after is not None:
        previous = read_cursor(after, scope)
        index = next((i for i, item in enumerate(items) if key(item) == previous), None)
        if index is None:
            raise ValueError("Cursor no longer belongs to this result")
        items = items[index + 1:]
    selected = items[:limit]
    return {"items": selected, "next_cursor":
            cursor(scope, key(selected[-1])) if len(items) > limit else None}


@contextmanager
def read_snapshot(store):
    """A deferred WAL read transaction never reserves the writer lock."""
    if store.connection.in_transaction:
        yield
    else:
        store.connection.execute("BEGIN")
        try:
            yield
        finally:
            store.connection.rollback()


def sessions(store, run_id):
    return [{
        "session_no": row["session_no"], "status": row["status"],
        "active_agents": store.connection.execute(
            "SELECT COUNT(*) FROM agent_sessions WHERE run_id=? AND session_id=? "
            "AND status!='inactive'", (run_id, row["session_id"])).fetchone()[0],
        "completed_agents": store.completed_agents(run_id, row["session_id"]),
        "posts": sorted(row["posts"], key=lambda p: p["position"]),
    } for row in store.sessions(run_id)]


def events(store, run_id):
    store.get_run(run_id)
    rows = store.sessions(run_id)
    return store.events_until_session(run_id, max(s["session_no"] for s in rows))


def event(row, session, include_all_scores=False):
    response = json.loads(row.get("model_response_json") or "{}")
    source = response.get("source")
    return public("Event", {
        **row, "session_no": session["session_no"], "session_status": session["status"],
        "score": row["normalized_score"],
        "source": source if source in {"jev", "llm_fallback"} else None,
        "tags": [{
            "tag_id": tag["tag_id"], "score": tag["normalized_score"],
            "selected": bool(tag["selected"]), "rank": tag["rank"],
            "description": tag["description"],
        } for tag in row["tags"] if include_all_scores or tag["selected"]],
    })


def recent_events(store, run_id, limit=20):
    by_session = {s["session_id"]: s for s in store.sessions(run_id)}
    return [event(row, by_session[row["session_id"]])
            for row in store.recent_events(run_id, limit)]

def history(store, run_id, agent_id, *, limit, after, session_no=None,
            object_type=None, object_id=None, stage=None, include_all_scores=False):
    if not any(a["agent_id"] == agent_id for a in store.agents(run_id)):
        raise BackendNotFoundError("Unknown run/agent")
    filters = {"session_no": session_no, "object_type": object_type,
               "object_id": object_id, "stage": stage}
    scope = json.dumps(["history", run_id, agent_id, filters, include_all_scores], sort_keys=True)
    by_session = {s["session_id"]: s for s in store.sessions(run_id)}
    # ponytail: MVP is bounded to 100 agents/20 sessions; push these filters
    # into SQL when measured history size warrants a paged query.
    items = [
        event(e, by_session[e["session_id"]], include_all_scores)
        for e in store.events_for_agent(
            run_id, agent_id, session_no=session_no, object_type=object_type,
            object_id=object_id, stage=stage,
        )
    ]
    return page(items, scope=scope, key=lambda e: e["event_id"], limit=limit, after=after)


def metric_point(store, row):
    watermark = store.connection.execute(
        "SELECT commit_seq FROM run_updates WHERE run_id=? AND "
        "update_type='session_completed' AND json_extract(payload_json,'$.session_no')=?",
        (row["run_id"], row["session_no"])).fetchone()
    return public("MetricPoint", {**row, "projected_through_seq": watermark[0] if watermark else 0})


_LABELS = {
    "posts_exposed": "Lượt gặp bài viết", "posts_attended": "Lượt chú ý bài viết",
    "posts_skipped": "Lượt bỏ qua bài viết", "posts_read": "Lượt đọc bài viết",
    "likes_added": "Lượt chọn thích", "dislikes_added": "Lượt chọn không thích",
    "current_likes": "Số phản ứng thích hiện tại",
    "current_dislikes": "Số phản ứng không thích hiện tại",
    "no_reaction": "Lượt không phản ứng", "reactions_kept": "Lượt giữ phản ứng",
    "reactions_removed": "Lượt bỏ phản ứng", "no_new_reaction": "Lượt không thêm phản ứng",
    "shop_visits": "Lượt ghé cửa hàng", "shop_not_visits": "Lượt không ghé cửa hàng",
    "products_exposed": "Lượt gặp sản phẩm", "products_attended": "Lượt chú ý sản phẩm",
    "products_skipped": "Lượt bỏ qua sản phẩm", "buys": "Lượt mua", "not_buys": "Lượt không mua",
    "stage_events": "Số bước đã xử lý", "empty_result": "Số bước không chọn được đáp án",
    "unresolved": "Số bước chưa giải quyết", "post_attention_rate": "Tỷ lệ chú ý bài viết",
    "read_rate": "Tỷ lệ đọc sau chú ý", "shop_visit_rate": "Tỷ lệ quyết định ghé cửa hàng",
    "product_attention_rate": "Tỷ lệ chú ý sản phẩm", "purchase_rate": "Tỷ lệ quyết định mua",
}


def metric_definitions(bundle):
    result = []
    statuses = {"resolved": "đã giải quyết", "empty_result": "không chọn được đáp án",
                "unresolved": "chưa giải quyết"}
    for name in sorted(metric_names(bundle)):
        label = _LABELS.get(name)
        if name.startswith("stage."):
            _, stage, status = name.split(".")
            label = f"Số bước {stage} {statuses[status]}"
        elif name.startswith("tag."):
            stage = name.split(".")[1]
            # Tag IDs can contain dots; retain the full ID.
            tag_id = name[len(f"tag.{stage}."):-len(".selected")]
            label = f"Lượt chọn thẻ {tag_id} tại {stage}"
        elif name.startswith("resolved_source."):
            label = f"Số bước giải quyết bằng {name.split('.', 1)[1]}"
        description = f"Đếm {label.lower()} trong phạm vi được chọn."
        if name in GAUGES:
            description = "Trạng thái phản ứng cuối phiên; không cộng các phiên với nhau."
        elif name in RATES:
            num, den = RATES[name]
            description = f"{num} chia {den}; mẫu số bằng 0 trả null. Lũy kế dùng tổng tử/mẫu."
        result.append({
            "name": name, "label_vi": label, "description_vi": description,
            "unit": "ratio" if name in RATES else "count",
            "kind": "rate" if name in RATES else "state" if name in GAUGES else "counter",
            "scopes": [s for s in ("run", "article", "shop", "product")
                       if name in _scope_metric_names(s, bundle)],
            "calculation_version": CALCULATION_VERSION,
        })
    return result


def usage(store, run_id):
    by_session = {}
    keys = ("input_tokens", "output_tokens", "total_tokens")
    def empty():
        return {"attempts": 0, "usage_missing_attempts": 0, **dict.fromkeys(keys)}
    total = empty()
    for row in store.connection.execute(
        "SELECT s.session_no, m.response_json FROM model_calls m "
        "JOIN stage_contexts c ON (m.stage_key=c.stage_key OR m.stage_key=c.stage_key || '#fallback') "
        "JOIN run_sessions s ON s.session_id=c.session_id WHERE c.run_id=? "
        "ORDER BY s.session_no, m.created_at", (run_id,)):
        part = by_session.setdefault(row["session_no"], empty())
        recorded = json.loads(row["response_json"] or "{}").get("usage") or {}
        valid = {k: recorded[k] for k in keys
                 if type(recorded.get(k)) is int and recorded[k] >= 0}
        for target in (part, total):
            target["attempts"] += 1
            target["usage_missing_attempts"] += len(valid) != len(keys)
            for key, value in valid.items():
                target[key] = (target[key] or 0) + value
    return {**total, "by_session": [
        {"session_no": number, **value} for number, value in by_session.items()]}


def report(store, run_id):
    run = store.get_run(run_id)
    return {
        "run": public("Run", run), "partial": run["status"] != "completed",
        "sessions": [s for s in sessions(store, run_id) if s["status"] == "completed"],
        "metrics": [metric_point(store, row) for row in
                    store.metric_snapshots(run_id, CALCULATION_VERSION)],
        "usage": usage(store, run_id),
    }

"""Shared polling/SSE projection from committed updates, separate from writer."""

from simulation.metrics.projector import (
    CALCULATION_VERSION, RATES, _scope_events, _scope_metric_names, summarize,
)
from . import views


def progress(store, run_id):
    with views.read_snapshot(store):
        run = store.get_run(run_id)
        current = store.progress(run_id)
        sessions = views.sessions(store, run_id)
        completed = [s for s in sessions if s["status"] == "completed"]
        active = next((s for s in sessions if s["status"] in {"running", "failed"}), None)
        if active is None:
            active = next((s for s in sessions if s["status"] == "pending"), sessions[-1])
        snapshot = store.run_snapshot(run_id)
        bundle = store.run_bundle(run_id)
        events = views.events(store, run_id)
        scopes = [("run", run_id)]
        scopes += [("article", p["post_id"]) for p in snapshot["posts"]]
        scopes += [("shop", s["shop_id"]) for s in snapshot["shops"]]
        scopes += [("product", p["product_id"]) for p in snapshot["products"]]
        counters = []
        for scope_type, scope_id in scopes:
            counts = summarize(_scope_events(snapshot, events, scope_type, scope_id))
            counters.append({
                "scope_type": scope_type, "scope_id": scope_id,
                "values": {name: counts[name]
                           for name in sorted(_scope_metric_names(scope_type, bundle) - RATES.keys())},
            })
        return {
            "run_id": run_id, "status": run["status"], "execution_epoch": run["execution_epoch"],
            "cursor": views.cursor(f"updates:{run_id}", current["cursor"]),
            "session_no": active["session_no"],
            "latest_completed_session_no": completed[-1]["session_no"] if completed else None,
            "active_agents": active["active_agents"], "completed_agents": active["completed_agents"],
            "provisional": run["status"] != "completed", "counters": counters,
        }


def after_sequence(store, run_id, after):
    latest = store.progress(run_id)["cursor"]
    value = views.read_cursor(after, f"updates:{run_id}") if after is not None else 0
    if type(value) is not int or not 0 <= value <= latest:
        raise ValueError("Cursor exceeds the committed watermark")
    return value


def updates(store, run_id, *, after=None, limit=50):
    with views.read_snapshot(store):
        sequence = after_sequence(store, run_id, after)
        run = store.get_run(run_id)
        latest = store.progress(run_id)["cursor"]
        if latest == sequence:
            return {"items": [], "next_cursor": after}
        live = progress(store, run_id)

        def message(kind, seq, payload=None, **extra):
            payload = payload or {}
            return {
                "type": kind, "run_id": run_id,
                "cursor": views.cursor(f"updates:{run_id}", seq),
                "execution_epoch": payload.get("execution_epoch", run["execution_epoch"]),
                "status": run["status"], "events": [],
                "session_no": payload.get("session_no", live["session_no"]),
                "metrics_ready": kind in {"session_completed", "run_completed"},
                "resync_required": False, "failure_code": None, **extra,
            }

        # Terminal notification deliberately supersedes animation backlog.
        # All events remain available through the paged history endpoint.
        if run["status"] in {"completed", "failed"}:
            kind = "run_completed" if run["status"] == "completed" else "run_failed"
            extra = {"latest_completed_session_no": live["latest_completed_session_no"]}
            if kind == "run_completed":
                extra["report_ready"] = True
            item = message(kind, latest, resync_required=True,
                           failure_code=run["failure_code"], **extra)
            return {"items": [item], "next_cursor": item["cursor"]}
        epoch_start = store.connection.execute(
            "SELECT MAX(commit_seq) FROM run_updates WHERE run_id=? "
            "AND update_type='run_started'", (run_id,)).fetchone()[0]
        if run["execution_epoch"] > 0 and sequence < (epoch_start or 0):
            # Do not replay an earlier epoch's run_failed into a resumed run.
            item = message("reset", latest, resync_required=True, progress=live)
            return {"items": [item], "next_cursor": item["cursor"]}
        if latest - sequence > 1000:
            item = message("reset", latest, resync_required=True, progress=live)
            return {"items": [item], "next_cursor": item["cursor"]}

        rows = store.updates_after(run_id, sequence, limit)
        by_id = {e["event_id"]: e for e in views.events(store, run_id)}
        by_session = {s["session_id"]: s for s in store.sessions(run_id)}
        result = []
        for row in rows:
            kind, payload, seq = row["type"], row["payload"], row["commit_seq"]
            if kind == "stage_event":
                raw = by_id[payload["event_id"]]
                event = views.event(raw, by_session[raw["session_id"]])
                if (result and result[-1]["type"] == "progress_batch"
                        and result[-1]["session_no"] == event["session_no"]
                        and len(result[-1]["events"]) < 100):
                    result[-1]["events"].append(event)
                    result[-1]["cursor"] = views.cursor(f"updates:{run_id}", seq)
                else:
                    result.append(message("progress_batch", seq,
                                          {"session_no": event["session_no"]},
                                          events=[event], progress=live))
            elif kind == "session_completed":
                result.append(message(
                    kind, seq, payload, calculation_version=CALCULATION_VERSION,
                    metrics_watermark=seq))
            elif kind == "run_started":
                result.append(message(kind, seq, payload, progress=live))
            else:
                result.append(message(kind, seq, payload, status=payload["status"],
                                      failure_code=payload.get("failure_code")))
        return {"items": result, "next_cursor": result[-1]["cursor"] if result else after}

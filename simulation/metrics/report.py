"""Read committed session metrics and agent history, without invoking models."""

from .projector import CALCULATION_VERSION, _scope_metric_names


class ReportService:
    def __init__(self, store):
        self.store = store

    def run_report(self, run_id):
        status = self.store.run_status(run_id)
        if status is None:
            raise ValueError("Unknown run")
        sessions = {}
        for row in self.store.metric_snapshots(run_id, CALCULATION_VERSION):
            if row["scope_type"] != "run":
                continue
            session = sessions.setdefault(row["session_id"], {
                "session_id": row["session_id"], "session_no": row["session_no"],
                "metrics": {},
            })
            session["metrics"][row["metric_name"]] = {
                key: row[key] for key in (
                    "numerator", "denominator", "session_value",
                    "cumulative_numerator", "cumulative_denominator", "cumulative_value")
            }
        completed = list(sessions.values())
        return {
            "run_id": run_id, "status": status,
            "calculation_version": CALCULATION_VERSION,
            "latest_completed_session_no": completed[-1]["session_no"] if completed else None,
            "sessions": completed,
            "model_usage": self.store.model_usage(run_id),
        }

    def metric_series(self, run_id, metric_name, *, scope_type="run", scope_id=None):
        if self.store.run_status(run_id) is None:
            raise ValueError("Unknown run")
        scope_id = run_id if scope_id is None else scope_id
        snapshot = self.store.run_snapshot(run_id)
        scopes = {"run": {run_id}, "article": {p["post_id"] for p in snapshot["posts"]},
                  "shop": {s["shop_id"] for s in snapshot["shops"]},
                  "product": {p["product_id"] for p in snapshot["products"]}}
        if scope_id not in scopes.get(scope_type, set()):
            raise ValueError("Unknown metric scope")
        if metric_name not in _scope_metric_names(scope_type, self.store.run_bundle(run_id)):
            raise ValueError("Metric does not apply to this scope")
        return [row for row in self.store.metric_snapshots(
            run_id, CALCULATION_VERSION, metric_name=metric_name)
                if row["scope_type"] == scope_type and row["scope_id"] == scope_id]

    def agent_history(self, run_id, agent_id, *, session_id=None, include_all_scores=False):
        """Ordered events plus scored tags; raw model requests remain in audit storage."""
        if not any(a["agent_id"] == agent_id for a in self.store.agents(run_id)):
            raise ValueError("Unknown run/agent")
        sessions = self.store.sessions(run_id)
        if session_id is not None and not any(s["session_id"] == session_id for s in sessions):
            raise ValueError("Unknown run/session")
        by_id = {s["session_id"]: s for s in sessions}
        if not by_id:
            return []
        # ponytail: small-run drill-down; add SQL pagination when history grows.
        return [
            {**{k: v for k, v in e.items() if k not in {"model_response_json", "stage_key", "tags"}},
             "tags": [t for t in e["tags"] if include_all_scores or t["selected"]],
             "session_no": by_id[e["session_id"]]["session_no"],
             "session_status": by_id[e["session_id"]]["status"]}
            for e in self.store.events_until_session(run_id, max(s["session_no"] for s in sessions))
            if e["agent_id"] == agent_id
            and (session_id is None or e["session_id"] == session_id)
        ]

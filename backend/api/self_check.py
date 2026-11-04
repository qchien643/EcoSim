"""Offline HTTP contract check on a real SQLite file; never calls a provider.

Run from ecoSim: .venv/bin/python -m backend.api.self_check
"""

import importlib
import json
import os
import re
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.contracts import SPEC, issues_for
from backend.runtime import BackendRunExecutor
from backend.self_check import fixture
from backend.store import BackendStore
from simulation.execution.self_check import ScriptedGateway, _prepare
from . import views

api = importlib.import_module("backend.api.app")


def main():
    from backend.templates_self_check import main as check_templates
    checked = check_templates()
    with TemporaryDirectory(prefix="ecosim-api-contract-") as directory:
        path = Path(directory) / "backend.sqlite"
        store = BackendStore(path)
        _prepare(store, agent_count=8, repeat_post=True, multi_product=True)
        with patch.dict(os.environ, {"ECOSIM_DATABASE": str(path)}), \
                patch.object(api, "_run_in_background") as worker, TestClient(api.app) as client:
            def request(method, url, status=200, **kwargs):
                response = client.request(method, "/api/v1" + url, **kwargs)
                assert response.status_code == status, (method, url, response.status_code, response.text[:1000])
                route = next(p for p in SPEC["paths"]
                             if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", p), url))
                operation = SPEC["paths"][route][method.lower()]
                schema = operation["responses"].get(str(status), operation["responses"]["default"])
                if "$ref" in schema:
                    schema = SPEC["components"]["responses"][schema["$ref"].rsplit("/", 1)[-1]]
                if status == 204:
                    assert response.content == b""
                    return response
                if "text/event-stream" in schema["content"]:
                    frames = [json.loads(line[6:]) for line in response.text.splitlines()
                              if line.startswith("data: ")]
                    assert frames
                    for frame in frames:
                        assert not issues_for(frame, "StreamMessage"), frame
                    checked.add((route, method.lower()))
                    return frames
                value = response.json()
                errors = issues_for(value, schema["content"]["application/json"]["schema"])
                assert not errors, (method, route, errors, str(value)[:500])
                if status < 400:
                    checked.add((route, method.lower()))
                return value

            for url in ("/industries", "/industries/cafe/profiles/cafe-mvp-v1",
                        "/datasets", "/cohorts"):
                request("GET", url)
            members = request("GET", "/cohorts/cohort_cafe_2/members", params={"limit": 3})
            more = request("GET", "/cohorts/cohort_cafe_2/members",
                           params={"limit": 3, "after": members["next_cursor"]})
            assert not {p["cohort_persona_id"] for p in members["items"]} & {
                p["cohort_persona_id"] for p in more["items"]}
            campaign = request("POST", "/campaigns", 201, json={"name": "HTTP test", "brief": "Offline"})
            cid = campaign["campaign_id"]
            request("GET", "/campaigns")
            request("GET", f"/campaigns/{cid}")
            request("PUT", f"/campaigns/{cid}", json={
                "expected_revision": 1, "campaign": {"name": "Updated", "brief": "Offline"}})
            request("PUT", f"/campaigns/{cid}", 409, json={
                "expected_revision": 1, "campaign": {"name": "Stale", "brief": "Offline"}})
            request("POST", "/campaigns", 422, json={"name": "N", "brief": "B", "unknown": "no"})
            draft = request("POST", f"/campaigns/{cid}/scenarios", 201, json={"name": "Draft"})
            sid = draft["scenario_id"]
            invalid = request("POST", f"/scenarios/{sid}/validate", json={"expected_revision": 1})
            assert invalid["valid"] is False and invalid["issues"]
            request("GET", f"/scenarios/{sid}/participants", 422)
            setup = fixture()
            setup["agent_count"] = 8
            setup["sessions"][1]["posts"] = [{"post_id": "post_demo", "position": 1}]
            setup["products"].append({**setup["products"][0], "product_id": "second_product", "position": 2})
            request("PUT", f"/scenarios/{sid}", json={"expected_revision": 1, "setup": setup})
            request("GET", f"/campaigns/{cid}/scenarios")
            request("GET", f"/scenarios/{sid}")
            request("POST", f"/scenarios/{sid}/validate", 409, json={"expected_revision": 1})
            request("POST", f"/scenarios/{sid}/validate", 422, json={})
            validated = request("POST", f"/scenarios/{sid}/validate", json={"expected_revision": 2})
            assert validated["valid"] and validated["group_counts"][0]["assigned_count"] == 8
            for field, value in (("active", ["agent_missing"]), ("industry", {"unregistered": True})):
                invalid_setup = deepcopy(setup)
                if field == "active":
                    invalid_setup["sessions"][0]["active_agent_ids"] = value
                else:
                    invalid_setup["products"][0]["industry_data"] = value
                invalid_draft = request("POST", f"/campaigns/{cid}/scenarios", 201, json=invalid_setup)
                result = request("POST", f"/scenarios/{invalid_draft['scenario_id']}/validate",
                                 json={"expected_revision": 1})
                assert not result["valid"]
            preview = request("GET", f"/scenarios/{sid}/participants")
            request("POST", f"/scenarios/{sid}/freeze", json={"expected_revision": 2})
            payload = {"expected_revision": 2, "execution": {"mode": "sequential", "batch_size": 1}}
            run = request("POST", f"/scenarios/{sid}/runs", 201,
                          json=payload, headers={"Idempotency-Key": "http-create"})
            rid = run["run_id"]
            replay = request("POST", f"/scenarios/{sid}/runs", 201,
                             json=payload, headers={"Idempotency-Key": "http-create"})
            assert replay == run
            request("GET", f"/scenarios/{sid}/runs")
            base = f"/runs/{rid}"
            for suffix in ("", "/sessions", "/objects", "/metric-definitions", "/progress", "/report", "/events", "/updates"):
                request("GET", base + suffix)
            participants = request("GET", base + "/agents")["items"]
            assert participants == preview["items"]
            exported = request("GET", base + "/configuration")
            original = store.get_run(rid)
            assert exported["input_snapshot"] == original["input_snapshot"]
            assert exported["snapshot_hash"] == original["snapshot_hash"]
            download = client.get("/api/v1" + base + "/configuration")
            assert download.headers["content-type"].startswith("application/json")
            assert download.headers["content-disposition"] == \
                'attachment; filename="ecosim-run-configuration.json"'
            assert download.headers["cache-control"] == "no-store"
            request("GET", "/runs/missing_run/configuration", 404)
            request("PUT", f"/campaigns/{cid}", json={
                "expected_revision": 2,
                "campaign": {"name": "Changed after freeze", "brief": "Changed"},
            })
            assert request("GET", base + "/configuration") == exported
            assert worker.call_count == 0
            request("POST", base + "/start", 202, headers={"Idempotency-Key": "http-start"})
            request("POST", base + "/start", 202, headers={"Idempotency-Key": "http-start"})
            assert worker.call_count == 1
            first = request("GET", base + "/updates", params={"limit": 1})
            assert first["items"][0]["type"] == "run_started"
            assert views.read_cursor(first["next_cursor"], f"updates:{rid}") == 1

            # Exercise actual failure + resume without an external model.
            store.finish_run(rid, "failed", "OFFLINE_TEST")
            failed = request("GET", base + "/updates")
            assert failed["items"][0]["type"] == "run_failed"
            request("GET", base + "/stream")
            request("POST", base + "/resume", 202, headers={"Idempotency-Key": "http-resume"})
            reset = request("GET", base + "/updates", params={"after": first["next_cursor"]})
            assert reset["items"][0]["type"] == "reset" and reset["items"][0]["execution_epoch"] == 1
            resumed_cursor = reset["next_cursor"]

            # Observe streaming during execution on a separate read connection.
            class ObservedGateway(ScriptedGateway):
                checked_progress = False

                def decide(self, stage, context):
                    if len(self.calls) == 8:
                        page = request("GET", base + "/updates",
                                       params={"after": resumed_cursor, "limit": 2})
                        assert page["items"][-1]["cursor"] == page["next_cursor"]
                        sequence = views.read_cursor(page["next_cursor"], f"updates:{rid}")
                        assert sequence < store.progress(rid)["cursor"]
                        following = request("GET", base + "/updates",
                                            params={"after": page["next_cursor"], "limit": 2})
                        assert views.read_cursor(following["next_cursor"], f"updates:{rid}") > sequence
                        self.checked_progress = True
                    return super().decide(stage, context)

            gateway = ObservedGateway()
            # Keep observation deterministic; worker dispatch was stubbed above.
            # Parallel parity is covered separately by the runtime regression check.
            BackendRunExecutor(store).execute(rid, primary=gateway, claimed=True)
            assert gateway.checked_progress
            assert store.progress(rid)["cursor"] > 100
            report = request("GET", base + "/report")
            assert not report["partial"] and len(report["sessions"]) == 2
            assert report["usage"]["attempts"] == len(gateway.calls)
            assert report["usage"]["usage_missing_attempts"] == len(gateway.calls)
            assert report["usage"]["total_tokens"] is None
            assert report["usage"]["attempts"] == sum(p["attempts"] for p in report["usage"]["by_session"])
            for metric, expected in (("current_likes", [8, 8]), ("purchase_rate", [0, 0])):
                points = request("GET", base + "/metrics", params={
                    "scope_type": "run", "scope_id": rid, "metric_name": metric})
                assert [p["cumulative_value"] for p in points] == expected
            BackendRunExecutor(store).rebuild_metrics(rid)
            assert request("GET", base + "/report") == report
            for scope, identity, metric, expected in (
                ("run", rid, "products_attended", 16),
                ("article", "post_demo", "posts_read", 8),
                ("shop", "shop_demo", "shop_visits", 8),
                ("product", "product_demo", "products_attended", 8),
                ("product", "second_product", "products_attended", 8),
            ):
                points = request("GET", base + "/metrics",
                                 params={"scope_type": scope, "scope_id": identity, "metric_name": metric})
                assert [p["session_value"] for p in points] == [expected, expected]
                assert points[-1]["cumulative_value"] == expected * 2
                assert all(p["projected_through_seq"] > 0 for p in points)
            request("GET", base + "/metrics", 422, params={
                "scope_type": "article", "scope_id": "post_demo", "metric_name": "purchase_rate"})
            request("GET", base + "/metrics", 422, params={
                "scope_type": "product", "scope_id": "missing", "metric_name": "buys"})
            history_url = base + "/agents/agent_cafe_001/history"
            full = request("GET", history_url, params={"limit": 200})["items"]
            collected, after = [], None
            while True:
                params = {"limit": 3}
                if after:
                    params["after"] = after
                result = request("GET", history_url, params=params)
                collected.extend(result["items"])
                after = result["next_cursor"]
                if not after:
                    break
            assert collected == full and len(full) == 22
            filtered = request("GET", history_url, params={
                "session_no": 2, "object_type": "product", "object_id": "second_product", "stage": "B2"})
            assert len(filtered["items"]) == 1
            all_scores = request("GET", history_url, params={"stage": "A2", "include_all_scores": True})
            assert any(not tag["selected"] for e in all_scores["items"] for tag in e["tags"])
            assert all(t["description"] for e in all_scores["items"] for t in e["tags"])
            first_page = request("GET", history_url, params={"limit": 1})
            request("GET", history_url, 400, params={"stage": "B2", "after": first_page["next_cursor"]})
            request("GET", history_url, 400, params={"stage": "invalid"})
            request("GET", base + "/agents/missing/history", 404)
            terminal = request("GET", base + "/updates", params={"limit": 1})
            assert terminal["items"][0]["type"] == "run_completed"
            assert terminal["items"][0]["resync_required"]
            frames = request("GET", base + "/stream")
            assert frames == terminal["items"]
            request("GET", base + "/stream", 204, headers={"Last-Event-ID": terminal["next_cursor"]},
                    params={"after": "ignored-invalid-cursor"})
            request("GET", base + "/stream", 400, params={"after": "bad"})
            request("GET", base + "/stream", 400, params={
                "after": views.cursor("updates:wrong_run", 1)})
            request("GET", base + "/stream", 400, params={
                "after": views.cursor(f"updates:{rid}", 999999)})
            assert request("GET", base + "/updates",
                           params={"after": terminal["next_cursor"]})["items"] == []
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses = list(pool.map(
                    lambda _: client.get("/api/v1" + base + "/progress"), range(8)))
            assert all(r.status_code == 200 and not issues_for(r.json(), "Progress")
                       for r in responses)
            # Progress reads a coherent WAL snapshot while a writer commits.
            store.claim_run("run_runtime")
            reader = BackendStore(path)
            from .stream import progress
            with views.read_snapshot(reader):
                before = progress(reader, "run_runtime")
                store.finish_run("run_runtime", "failed", "OFFLINE_SNAPSHOT_CHECK")
                assert progress(reader, "run_runtime") == before
            assert progress(reader, "run_runtime")["status"] == "failed"
            reader.close()
            assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
        store.close()
    expected = {(path, method) for path, item in SPEC["paths"].items()
                for method in ("get", "post", "put") if method in item}
    assert checked == expected, expected - checked
    print(f"PASS: {len(checked)} HTTP operations match checked-in OpenAPI on file-backed SQLite")
    print("PASS: revisions, participant parity, scoped metrics, history filters/pagination, token coverage")
    print("PASS: polling cursor, resume epoch, terminal backlog >100, SSE reconnect/204 and error envelopes")
    print("PASS: concurrent HTTP readers, coherent WAL progress snapshot, metric rebuild and input boundaries")


if __name__ == "__main__":
    main()

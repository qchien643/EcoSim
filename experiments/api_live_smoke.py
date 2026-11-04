"""Small explicit paid API smoke run. Execute only with --live.

Uses real localhost HTTP, the normal background dispatcher, JEV and its
configured OpenAI fallback. No decision output or threshold is patched.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import httpx

from backend.bootstrap import bootstrap
from backend.self_check import fixture
from gateways.jev import default_jev_config
from gateways.openai import default_openai_config

ROOT = Path(__file__).resolve().parents[1]


def setup():
    data = fixture()
    data.update(name="API live smoke: 2 agent, 1 phiên",
                cohort_id="cafe-mvp-cohort-v1", selection_seed=20260930)
    data["sessions"] = data["sessions"][:1]
    data["business"].update(
        organization_name="Mộc Cafe — dữ liệu thử nghiệm",
        organization_description="Một doanh nghiệp cà phê địa phương tại Đà Nẵng.",
        brand_name="Mộc Cafe",
        brand_description="Cà phê địa phương, chú trọng cách pha chế và nguyên liệu.",
        tags=[{"tag_id": "enterprise.local_business",
               "source_ref": "organization:org_demo:organization_description",
               "visible_stages": ["A1", "A2", "A3", "B1", "B2"]}])
    data["shops"][0].update(
        name="Gian hàng Mộc Cafe", public_profile="Gian hàng trực tuyến của quán cà phê Mộc.")
    data["posts"][0].update(
        title="Ra mắt cà phê cam lạnh",
        preview="Mộc Cafe giới thiệu cà phê cam lạnh 39.000 đồng cho giờ nghỉ buổi chiều.",
        article_content=(
            "Mộc Cafe giới thiệu cà phê cam lạnh: cà phê ủ lạnh kết hợp hương cam, "
            "vị ngọt nhẹ, dùng với đá. Một ly giá 39.000 đồng. "
            "Ghé gian hàng để tìm hiểu món mới cho giờ nghỉ buổi chiều."),
        tags=[{"tag_id": tag, "source_ref": "post:post_demo:preview",
               "visible_stages": ["A1", "A2", "A3"]}
              for tag in ("article.product_introduction", "article.use_occasion")])
    data["products"][0].update(
        product_name="Cà phê cam lạnh",
        listed_price="39.000 VND",
        product_description="Cà phê ủ lạnh kết hợp hương cam, vị ngọt nhẹ, dùng với đá.",
        tags=[{"tag_id": tag, "source_ref": "product:product_demo:product_name",
               "visible_stages": ["B1", "B2", "B3"]}
              for tag in ("product.coffee_drink", "product.fruit_notes", "product.cold_serving")])
    return data


def save(directory, name, data):
    (directory / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def audit(database):
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(
            "SELECT c.stage, c.agent_id, m.provider, m.model, m.status, "
            "m.validation_status, m.error_code, m.elapsed_ms, m.response_json "
            "FROM model_calls m JOIN stage_contexts c "
            "ON (m.stage_key=c.stage_key OR m.stage_key=c.stage_key || '#fallback') "
            "ORDER BY m.created_at")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow paid calls through run start")
    args = parser.parse_args()
    jev, fallback = default_jev_config(), default_openai_config()
    directory = Path(tempfile.mkdtemp(prefix="api-live-smoke-", dir=ROOT / "experiments"))
    database = directory / "backend.sqlite"
    bootstrap(database)
    print("ARTIFACTS", directory, flush=True)
    save(directory, "scenario-input.json", setup())
    # Inherit one bound socket to avoid choosing an already-used port.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(64)
    port = listener.getsockname()[1]
    env = {**os.environ, "ECOSIM_DATABASE": str(database)}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.api.app:app",
         "--fd", str(listener.fileno()), "--workers", "1", "--log-level", "critical"],
        cwd=ROOT, env=env, pass_fds=(listener.fileno(),),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    listener.close()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}/api/v1",
                          timeout=10, trust_env=False) as client:
            for _ in range(50):
                try:
                    if client.get("/industries").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if server.poll() is not None:
                    raise RuntimeError("API server exited before startup")
                time.sleep(0.1)
            else:
                raise RuntimeError("API server did not become ready")

            def call(method, path, expected=200, **kwargs):
                response = client.request(method, path, **kwargs)
                if response.status_code != expected:
                    raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
                return response.json()

            campaign = call("POST", "/campaigns", 201, json={
                "name": "Mộc Cafe — live API smoke",
                "brief": "Giới thiệu cà phê cam lạnh cho giờ nghỉ chiều; nội dung thử nghiệm."})
            scenario = call("POST", f"/campaigns/{campaign['campaign_id']}/scenarios", 201,
                            json={"name": "Live API smoke"})
            sid = scenario["scenario_id"]
            scenario = call("PUT", f"/scenarios/{sid}",
                            json={"expected_revision": 1, "setup": setup()})
            revision = scenario["revision"]
            validation = call("POST", f"/scenarios/{sid}/validate",
                              json={"expected_revision": revision})
            save(directory, "validation.json", validation)
            if not validation["valid"]:
                raise RuntimeError("Scenario validation failed; see validation.json")
            participants = call("GET", f"/scenarios/{sid}/participants")
            save(directory, "participants.json", participants)
            call("POST", f"/scenarios/{sid}/freeze", json={"expected_revision": revision})
            run = call("POST", f"/scenarios/{sid}/runs", 201,
                       headers={"Idempotency-Key": "live-smoke-create"},
                       json={"expected_revision": revision,
                             "execution": {"mode": "sequential", "batch_size": 1}})
            rid = run["run_id"]
            save(directory, "run.json", run)
            if not args.live:
                print("PASS: actual HTTP setup/validation/freeze/run-ready; no model called.")
                return
            print("START", rid, "JEV", jev.model, "fallback", fallback.model, flush=True)
            start = time.monotonic()
            call("POST", f"/runs/{rid}/start", 202,
                 headers={"Idempotency-Key": "live-smoke-start"})
            last = None
            while True:
                run = call("GET", f"/runs/{rid}")
                attempts = audit(database)
                current = (run["status"], len(attempts), sum(a["status"] == "responded" for a in attempts))
                if current != last:
                    print("PROGRESS", current, "elapsed_s", round(time.monotonic() - start, 1), flush=True)
                    last = current
                if run["status"] in {"completed", "failed"}:
                    break
                time.sleep(1)
            wall_seconds = round(time.monotonic() - start, 3)
            report = call("GET", f"/runs/{rid}/report")
            histories = {}
            for agent in participants["items"]:
                histories[agent["agent_id"]] = call(
                    "GET", f"/runs/{rid}/agents/{agent['agent_id']}/history",
                    params={"limit": 200, "include_all_scores": True})
            save(directory, "run.json", run)
            save(directory, "report.json", report)
            save(directory, "agent-history.json", histories)
            for attempt in attempts:
                attempt["response"] = json.loads(attempt.pop("response_json") or "{}")
            save(directory, "model-attempts.json", attempts)
            summary = {
                "run_id": rid, "status": run["status"], "failure_code": run["failure_code"],
                "wall_seconds": wall_seconds, "agent_count": 2, "sessions": 1,
                "posts": 1, "products": 1,
                "providers": sorted({a["provider"] for a in attempts}),
                "usage": report["usage"],
                "metrics": {m["metric_name"]: m["cumulative_value"] for m in report["metrics"]
                            if m["scope_type"] == "run" and m["metric_name"] in {
                                "posts_attended", "posts_read", "current_likes", "current_dislikes",
                                "shop_visits", "products_attended", "buys", "not_buys", "unresolved"}},
            }
            save(directory, "summary.json", summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == "__main__":
    main()

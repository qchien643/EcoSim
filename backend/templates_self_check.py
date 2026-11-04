"""Offline template API check on real prepared personas and temporary SQLite."""

import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from .bootstrap import bootstrap
from .contracts import issues_for
from .store import BackendStore
from .templates import ROOT, get_template

api = importlib.import_module("backend.api.app")


def main():
    template_id = "cafe-50x4-v1"
    original = get_template(template_id)
    file_bytes = (ROOT / "cafe/cafe-50x4-v1.json").read_bytes()
    base = f"/api/v1/scenario-templates/{template_id}"
    payload = {"campaign": original["campaign"], "scenario_name": original["setup"]["name"]}
    with TemporaryDirectory(prefix="ecosim-templates-") as directory:
        database = Path(directory) / "backend.sqlite"
        with patch.dict(os.environ, {"ECOSIM_DATABASE": str(database)}), \
                patch.object(api, "_run_in_background") as worker, TestClient(api.app) as client:
            listed = client.get("/api/v1/scenario-templates")
            assert listed.status_code == 200
            assert len(listed.json()) >= 2
            assert not issues_for(listed.json()[0], "ScenarioTemplateSummary")
            template_summary = next(item for item in listed.json()
                                    if item["template_id"] == template_id)
            assert template_summary["product_count"] == 6
            assert template_summary["post_count"] == 7
            assert client.get(base).json() == original
            assert client.get("/api/v1/scenario-templates/unknown").status_code == 404
            assert client.get("/api/v1/scenario-templates/..%2F..%2F.env").status_code == 404
            url = base + "/instantiate"
            headers = {"Idempotency-Key": "template-first"}
            missing = client.post(url, json=payload, headers=headers)
            assert missing.status_code == 422, missing.text
            store = BackendStore(database)
            assert store.list_campaigns() == []
            assert store.connection.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0] == 0
            assert store.connection.execute("SELECT COUNT(*) FROM idempotency_keys").fetchone()[0] == 0
            bootstrap(database)

            assert client.post(url, json=payload).status_code == 422
            assert client.post(url, json=payload, headers={"Idempotency-Key": " "}).status_code == 422
            assert client.post(url, json={**payload, "setup": {}}, headers=headers).status_code == 422
            assert client.post("/api/v1/scenario-templates/unknown/instantiate",
                               json=payload, headers=headers).status_code == 404

            # A retry, even concurrent, must not create duplicate campaign/scenario pairs.
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: client.post(url, json=payload, headers=headers), range(2)))
            assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
            result = responses[0].json()
            assert result == responses[1].json()
            assert not issues_for(result, "TemplateInstantiationResult")
            assert len(store.list_campaigns()) == 1
            sid = result["scenario_id"]
            draft = client.get(f"/api/v1/scenarios/{sid}").json()
            assert draft["status"] == "draft" and draft["revision"] == 1
            assert not issues_for(draft, "Scenario")
            report = client.post(f"/api/v1/scenarios/{sid}/validate", json={"expected_revision": 1}).json()
            assert report["valid"], report
            assert sorted(g["assigned_count"] for g in report["group_counts"]) == [12, 12, 13, 13]
            participants = client.get(f"/api/v1/scenarios/{sid}/participants").json()
            assert len(participants["items"]) == 50
            setup = draft["setup"]
            assert setup["business"]["organization_id"] != original["setup"]["business"]["organization_id"]
            assert setup["business"]["brand_id"] != original["setup"]["business"]["brand_id"]
            for collection, field in (("shops", "shop_id"), ("posts", "post_id"),
                                      ("products", "product_id"), ("relationship_groups", "group_id")):
                assert not {x[field] for x in setup[collection]} & {x[field] for x in original["setup"][collection]}
            assert setup["sessions"][0]["posts"][0]["post_id"] == setup["sessions"][1]["posts"][0]["post_id"]
            assert all(t["tag_id"] in {tag["id"] for tag in store.industry_bundle("cafe", "cafe-mvp-v1")["tag_registry"]["tags"]}
                       for obj in [setup["business"], *setup["shops"], *setup["posts"], *setup["products"]]
                       for t in obj["tags"])

            changed = deepcopy(payload)
            changed["scenario_name"] = "Another request"
            assert client.post(url, json=changed, headers=headers).status_code == 409
            # Invalid template references must roll back the newly created campaign too.
            invalid = deepcopy(original)
            invalid["setup"]["products"][0]["tags"][0]["tag_id"] = "product.nonexistent"
            with patch("backend.templates.get_template", return_value=invalid):
                failed = client.post(url, json=payload, headers={"Idempotency-Key": "invalid-template"})
                assert failed.status_code == 422
            assert len(store.list_campaigns()) == 1

            # Editing one copy cannot modify the catalog or the next copy.
            setup["products"][0]["listed_price"] = "31.000 VND"
            updated = client.put(f"/api/v1/scenarios/{sid}", json={"expected_revision": 1, "setup": setup})
            assert updated.status_code == 200
            second = client.post(url, json=payload, headers={"Idempotency-Key": "template-second"})
            assert second.status_code == 201
            other = client.get(f"/api/v1/scenarios/{second.json()['scenario_id']}").json()
            assert other["setup"]["products"][0]["listed_price"] == "29.000 VND"
            assert other["setup"]["products"][0]["product_id"] != setup["products"][0]["product_id"]
            assert client.post(url, json=payload, headers=headers).json() == result
            assert client.post(f"/api/v1/scenarios/{sid}/freeze", json={"expected_revision": 2}).status_code == 200
            assert client.post(url, json=payload, headers=headers).json() == result
            assert store.connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
            assert store.connection.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0] == 0
            assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
            worker.assert_not_called()
            store.close()
    assert (ROOT / "cafe/cafe-50x4-v1.json").read_bytes() == file_bytes
    print("PASS: template API, real cohort, remapped references, draft editing, freeze, atomic rollback, concurrent retry; no provider calls")
    return {("/scenario-templates", "get"), ("/scenario-templates/{template_id}", "get"),
            ("/scenario-templates/{template_id}/instantiate", "post")}


if __name__ == "__main__":
    main()

"""Offline bootstrap checks; only temporary databases and scripted model calls."""

from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from .bootstrap import ROOT, bootstrap, install, prepare
from .contracts import issues_for
from .self_check import fixture
from .store import BackendConflictError, BackendStore
from simulation.execution.self_check import ScriptedGateway


def main():
    cohort_dir = ROOT / "data/personas/cafe_mvp"
    source_dir = ROOT / "data/matraix/persona_1m"
    prepared = prepare(cohort_dir, source_dir)
    cohort_id = prepared["cohort"]["cohort_id"]
    industry = prepared["industry"]
    with TemporaryDirectory(prefix="ecosim-bootstrap-") as directory:
        directory = Path(directory)
        database = directory / "backend.sqlite"
        first = bootstrap(database)
        second = bootstrap(database)
        assert all(first[k] == "inserted" and second[k] == "unchanged"
                   for k in ("dataset", "industry", "cohort"))
        store = BackendStore(database)
        assert first["cohort_size"] == 100
        assert len(store.cohort_members(cohort_id, 200)) == 100
        assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()

        api = importlib.import_module("backend.api.app")
        with patch.dict(os.environ, {"ECOSIM_DATABASE": str(database)}), \
                patch("gateways.jev.build_jev_gateway", return_value=ScriptedGateway()), \
                patch("gateways.openai.build_openai_gateway", return_value=ScriptedGateway()), \
                TestClient(api.app) as client:
            def request(method, path, status=200, **kwargs):
                response = client.request(method, "/api/v1" + path, **kwargs)
                assert response.status_code == status, (path, response.status_code, response.text[:300])
                return response.json()

            industries = request("GET", "/industries")
            assert len(industries) == 1 and not issues_for(industries[0], "Industry")
            datasets = request("GET", "/datasets")
            assert len(datasets) == 1 and not issues_for(datasets[0], "Dataset")
            assert datasets[0]["revision"] == prepared["dataset"]["revision"]
            cohorts = request("GET", "/cohorts")["items"]
            assert cohorts[0]["cohort_id"] == cohort_id and cohorts[0]["size"] == 100
            members, after = [], None
            while True:
                params = {"limit": 37}
                if after:
                    params["after"] = after
                page = request("GET", f"/cohorts/{cohort_id}/members", params=params)
                members.extend(page["items"])
                after = page["next_cursor"]
                if not after:
                    break
            assert len(members) == len({m["cohort_persona_id"] for m in members}) == 100
            assert all(not issues_for(m, "Persona") for m in members)
            for actual, expected in zip(members, prepared["cohort"]["members"]):
                assert actual["persona"] == expected["persona"]
                assert actual["field_provenance"] == expected["field_provenance"]
            campaign = request("POST", "/campaigns", 201, json={
                "name": "Bootstrap check", "brief": "Offline fixture; not a real campaign."})
            setup = fixture()
            setup.update(cohort_id=cohort_id, industry_id=industry["industry_id"],
                         profile_version=industry["profile_version"])
            scenario = request("POST", f"/campaigns/{campaign['campaign_id']}/scenarios", 201,
                               json=setup)
            sid = scenario["scenario_id"]
            assert request("POST", f"/scenarios/{sid}/validate",
                           json={"expected_revision": 1})["valid"]
            request("POST", f"/scenarios/{sid}/freeze", json={"expected_revision": 1})
            run = request("POST", f"/scenarios/{sid}/runs", 201,
                          headers={"Idempotency-Key": "bootstrap-check"},
                          json={"expected_revision": 1, "execution": {"mode": "sequential", "batch_size": 1}})
            rid = run["run_id"]
            request("POST", f"/runs/{rid}/start", 202,
                    headers={"Idempotency-Key": "bootstrap-start"})
            report = request("GET", f"/runs/{rid}/report")
            assert not issues_for(report, "Report") and report["run"]["status"] == "completed"
            contexts = store.connection.execute(
                "SELECT snapshot_json FROM stage_contexts WHERE run_id=? AND stage='A1'", (rid,)).fetchall()
            assert contexts
            # Re-import does not alter campaigns, frozen inputs, events or reports.
            bootstrap(database)
            assert request("GET", f"/runs/{rid}/report") == report

        # Verify actual stored members, not merely the hash column.
        with store.transaction() as db:
            db.execute("UPDATE cohort_members SET persona_json='{}' WHERE cohort_id=? "
                       "AND cohort_persona_id=?", (cohort_id, members[0]["cohort_persona_id"]))
        try:
            bootstrap(database)
        except BackendConflictError:
            pass
        else:
            raise AssertionError("Changed member content was accepted")
        assert store.connection.execute("SELECT persona_json FROM cohort_members WHERE cohort_id=? "
                                        "AND cohort_persona_id=?",
                                        (cohort_id, members[0]["cohort_persona_id"])).fetchone()[0] == "{}"
        store.close()

        # Inject a failure after the cohort and its rows were written.
        store = BackendStore(directory / "rollback.sqlite")
        register = store.register_cohort
        def broken_register(**kwargs):
            register(**kwargs)
            raise RuntimeError("Injected failure")
        with patch.object(store, "register_cohort", side_effect=broken_register):
            try:
                install(store, prepared)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Injected failure not reached")
        for table in ("persona_datasets", "industry_profiles", "persona_cohorts", "cohort_members"):
            assert store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert install(store, prepared)["cohort"] == "inserted"
        changed = deepcopy(prepared)
        changed["industry"]["bundle"]["profile"]["notes"].append("changed asset")
        try:
            install(store, changed)
        except BackendConflictError:
            pass
        else:
            raise AssertionError("Bundle drift accepted under existing version")
        store.close()

        # Trust-boundary checks operate on private temporary input copies.
        inputs = directory / "inputs"
        inputs.mkdir()
        manifest = json.loads((cohort_dir / "manifest.json").read_text())
        rows = [json.loads(line) for line in (cohort_dir / "cohort.jsonl").read_text().splitlines()]
        (inputs / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        cases = []
        invalid = deepcopy(rows)
        invalid[0]["persona"]["trait_curiosity"] = "NOT_AN_ENUM"
        cases.append(invalid)
        invalid = deepcopy(rows)
        invalid[0]["field_provenance"].pop("trait_curiosity")
        cases.append(invalid)
        invalid = deepcopy(rows)
        invalid[0]["persona"].pop("trait_curiosity")
        cases.extend([invalid, rows[:-1], [rows[0], rows[0], *rows[2:]]])
        for invalid in cases:
            (inputs / "cohort.jsonl").write_text(
                "\n".join(json.dumps(row) for row in invalid), encoding="utf-8")
            try:
                bootstrap(directory / "invalid.sqlite", cohort_dir=inputs)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid input accepted")
            assert not (directory / "invalid.sqlite").exists()
        legacy = directory / "legacy.sqlite"
        with sqlite3.connect(legacy) as db:
            db.execute("CREATE TABLE old_data (value TEXT)")
            db.execute("INSERT INTO old_data VALUES ('preserve')")
        try:
            bootstrap(legacy)
        except BackendConflictError:
            pass
        else:
            raise AssertionError("Old database accepted")
        with sqlite3.connect(legacy) as db:
            assert db.execute("SELECT value FROM old_data").fetchone()[0] == "preserve"
    print("PASS: 100 managed personas, enums/provenance, API pagination and full offline run")
    print("PASS: idempotency, frozen-run preservation, atomic rollback and drift rejection")
    print("PASS: invalid/missing/duplicate input rejected before DB creation; legacy DB preserved")


if __name__ == "__main__":
    main()

"""Offline regression gates for the new backend; no provider requests."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import sqlite3

from backend.runtime import BackendRunExecutor
from backend.store import BackendStore, BackendConflictError
from gateways.jev import GatewayUnavailable
from simulation.execution.self_check import ScriptedGateway, _prepare


def semantic_history(store):
    return [
        tuple(event[key] for key in (
            "agent_id", "session_id", "sequence_no", "object_type", "object_id",
            "stage", "encounter_no", "status", "action", "normalized_score"
        )) + (tuple((t["tag_id"], t["normalized_score"], t["selected"])
                    for t in event["tags"]),)
        for event in store.events_until_session("run_runtime", 2)
    ]


def parity(root):
    results = []
    for mode in ("sequential", "parallel"):
        store = BackendStore(root / f"{mode}.sqlite")
        try:
            _prepare(store, repeat_post=True, agent_count=4,
                     mode=mode, batch_size=4 if mode == "parallel" else 1,
                     multi_product=True, inactive_first=True)
            BackendRunExecutor(store).execute("run_runtime", primary=ScriptedGateway())
            history = semantic_history(store)
            # Three participants first session, all four second; 11 stages per encounter.
            assert len(history) == 77, len(history)
            first = store.connection.execute(
                "SELECT encounter_no FROM stage_events "
                "WHERE agent_id='agent_cafe_001' AND stage='A1'"
            ).fetchall()
            assert [row[0] for row in first] == [1], first
            results.append((history, store.metric_snapshots("run_runtime", "metrics-v1")))
            assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            store.close()
    assert results[0] == results[1], "Parallel mode changed behavior or metrics"
    print("PASS: 4-agent sequential/parallel parity, 2 products, inactive agent, repeat memory")


def rollback_resume(root):
    path = root / "resume.sqlite"
    store = BackendStore(path)
    _prepare(store, repeat_post=True)
    gateway = ScriptedGateway()
    # Fail inside event transaction, after tags/state/checkpoint were written.
    original = BackendStore._append_update
    failed = False
    def fail_once(self, db, run_id, kind, payload):
        nonlocal failed
        if kind == "stage_event" and payload["stage"] == "A3" and not failed:
            failed = True
            raise sqlite3.OperationalError("injected stage write failure")
        return original(self, db, run_id, kind, payload)
    try:
        with patch.object(BackendStore, "_append_update", fail_once):
            try:
                BackendRunExecutor(store).execute("run_runtime", primary=gateway)
            except sqlite3.OperationalError:
                pass
            else:
                raise AssertionError("Injected write failure did not propagate")
        assert store.run_status("run_runtime") == "failed"
        assert not store.metric_snapshots("run_runtime", "metrics-v1")
        assert store.connection.execute(
            "SELECT COUNT(*) FROM stage_events WHERE stage='A3'"
        ).fetchone()[0] == 0
        first_agent = store.run_agents("run_runtime")[0]["agent_id"]
        history = BackendRunExecutor(store).agent_history("run_runtime", first_agent)
        assert [e["stage"] for e in history] == ["A1", "A2"]
        assert history[0]["session_status"] == "failed"
        cached = store.connection.execute(
            "SELECT call_id FROM model_calls WHERE stage_key LIKE '%|A3' AND status='responded'"
        ).fetchone()[0]
        store.close()
        store = BackendStore(path)
        BackendRunExecutor(store).execute("run_runtime", primary=gateway, resume=True)
        assert store.run_status("run_runtime") == "completed"
        assert len(gateway.calls) == 32, "Resume repeated a persisted response"
        assert store.connection.execute(
            "SELECT event_id FROM model_calls WHERE call_id=?", (cached,)
        ).fetchone()[0] is not None
        assert len(semantic_history(store)) == 32
        assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
        before = store.metric_snapshots("run_runtime", "metrics-v1")
        cursor = store.progress("run_runtime")["cursor"]
        BackendRunExecutor(store).rebuild_metrics("run_runtime")
        assert store.metric_snapshots("run_runtime", "metrics-v1") == before
        assert store.progress("run_runtime")["cursor"] == cursor
        print("PASS: stage rollback, failed-session history, file reopen, cached-response resume, metrics rebuild")
    finally:
        store.close()


def command_guard(root):
    store = BackendStore(root / "commands.sqlite")
    try:
        _prepare(store)
        run = store.get_run("run_runtime")
        store.create_run(run["scenario_id"], {"mode": "sequential", "batch_size": 1},
                         "second_run")
        first = store.claim_command("run_runtime", operation="start_run", idempotency_key="start")
        replay = store.claim_command("run_runtime", operation="start_run", idempotency_key="start")
        assert first["newly_claimed"] and not replay["newly_claimed"]
        try:
            store.claim_run("second_run")
        except BackendConflictError:
            pass
        else:
            raise AssertionError("Two running runs admitted")
        assert store.get_run("second_run")["status"] == "ready"
        print("PASS: idempotent start and one-running-run admission")
    finally:
        store.close()


class FailingPrimary:
    provider = "primary"
    model = "unavailable"

    def decide(self, stage, context):
        raise GatewayUnavailable("offline test failure")


def fallback_attempt_audit(root):
    store = BackendStore(root / "fallback.sqlite")
    try:
        _prepare(store)
        BackendRunExecutor(store).execute(
            "run_runtime",
            primary=FailingPrimary(),
            fallback=ScriptedGateway(),
        )
        failures = store.connection.execute(
            "SELECT COUNT(*) FROM model_calls "
            "WHERE status='failed' AND error_code='provider_unavailable'"
        ).fetchone()[0]
        responses = store.connection.execute(
            "SELECT COUNT(*) FROM model_calls WHERE status='responded'"
        ).fetchone()[0]
        assert failures > 0
        assert responses > 0
        assert store.connection.execute(
            "SELECT COUNT(*) FROM model_calls "
            "WHERE status='failed' AND response_json IS NOT NULL"
        ).fetchone()[0] == 0
        print("PASS: provider failure stays failed and fallback uses separate attempts")
    finally:
        store.close()


def main():
    with TemporaryDirectory(prefix="ecosim-regression-") as directory:
        root = Path(directory)
        parity(root)
        rollback_resume(root)
        command_guard(root)
        fallback_attempt_audit(root)


if __name__ == "__main__":
    main()

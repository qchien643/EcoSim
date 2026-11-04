"""Explicitly paid benchmark: python3 -m experiments.jev_parallel_benchmark --live.

Four synthetic agents, one session, same scenario in both modes. No fallback,
no retries, at most 44 requests per mode. Records no authorization headers.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import mkdtemp
from threading import Lock
from time import perf_counter

from gateways.jev import RouterPoolGateway, default_jev_config
from simulation.orchestrator import RunCoordinator
from simulation.parallel_self_check import four_agent_scenario
from simulation.metrics.report import ReportService
from simulation.decision.stage import StageService
from simulation.store_sqlite import SqliteSimulationStore


def run_mode(directory, mode, config):
    records, active, peak = [], 0, 0
    lock = Lock()
    started = perf_counter()

    class MeasuredGateway(RouterPoolGateway):
        def _request(self, router, payload, endpoint):
            nonlocal active, peak
            begin = perf_counter()
            with lock:
                active += 1
                peak = max(peak, active)
            record = {"start_seconds": begin - started, "request": payload}
            try:
                raw = super()._request(router, payload, endpoint)
                record["response"] = raw
                record["status"] = "ok"
                return raw
            except Exception as error:
                record["status"] = type(error).__name__
                record["http_status"] = getattr(error, "code", None)
                raise
            finally:
                record["elapsed_seconds"] = perf_counter() - begin
                with lock:
                    active -= 1
                    records.append(record)

    def stages(store):
        return StageService(store, MeasuredGateway(
            [config], source="jev",
            headers={"X-OpenRouter-Title": "ProjectDut four-agent mode benchmark"}))

    scenario = four_agent_scenario("run_mode_benchmark")
    scenario["sessions"] = scenario["sessions"][:1]
    store = SqliteSimulationStore(directory / f"{mode}.sqlite")
    coordinator = RunCoordinator(store, stages(store), execution_mode=mode,
                                 batch_size=4, worker_stage_factory=stages)
    summary = {"mode": mode, "agents": 4, "sessions": 1, "batch_size": 4}
    try:
        coordinator.run(scenario)
    except Exception as error:
        summary["error_type"] = type(error).__name__
    summary["wall_seconds"] = perf_counter() - started
    summary["requests"] = len(records)
    summary["http_successes"] = sum(r["status"] == "ok" for r in records)
    summary["peak_in_flight"] = peak
    summary["sum_http_seconds"] = sum(r["elapsed_seconds"] for r in records)
    summary["events_by_stage_status"] = [dict(row) for row in store.connection.execute(
        "SELECT stage, status, COUNT(*) AS count FROM stage_events "
        "GROUP BY stage, status ORDER BY stage, status")]
    summary["events"] = store.connection.execute("SELECT COUNT(*) FROM stage_events").fetchone()[0]
    summary["report"] = ReportService(store).run_report(scenario["run_id"])
    assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
    store.close()
    (directory / f"{mode}-requests.json").write_text(
        json.dumps(sorted(records, key=lambda r: r["start_seconds"]),
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; this calls the paid JEV API")
    config = default_jev_config()
    directory = Path(mkdtemp(prefix="jev-mode-benchmark-", dir=Path(__file__).parent))
    result = {"created_at": datetime.now(timezone.utc).isoformat(),
              "fixture": "simulation.parallel_self_check.four_agent_scenario; synthetic",
              "artifact_directory": str(directory), "modes": []}
    for mode in ("sequential", "parallel"):
        summary = run_mode(directory, mode, config)
        result["modes"].append(summary)
        print(json.dumps({k: v for k, v in summary.items()
                          if k not in {"report", "events_by_stage_status"}}, indent=2), flush=True)
        (directory / "summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if summary.get("error_type"):
            break
    print(f"Artifacts: {directory}", flush=True)


if __name__ == "__main__":
    main()

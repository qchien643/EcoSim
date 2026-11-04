"""Backend run lifecycle and reporting.

The runtime uses the single backend SQLite database. It does not materialize
or execute a second, legacy simulation database.
"""

from __future__ import annotations

from typing import Any

from simulation.decision.stage import StageService
from simulation.execution.coordinator import RunCoordinator
from simulation.metrics.projector import MetricsProjector

from .store import BackendStore
from .persistence.writer import RunWriter


class BackendRunExecutor:
    def __init__(self, backend_store: BackendStore):
        self.store = backend_store

    def execute(
        self, run_id: str, *, primary: Any, fallback: Any | None = None,
        resume: bool = False, claimed: bool = False,
    ) -> dict[str, Any]:
        current = self.store.get_run(run_id)
        if current["status"] == "completed":
            return current
        if not claimed:
            self.store.claim_run(run_id, resume=resume)
        current = self.store.get_run(run_id)
        execution = current["execution"]
        writer = None
        try:
            writer = RunWriter(self.store.database_path)
            stages = StageService(writer, primary, fallback)
            coordinator = RunCoordinator(
                writer, stages, execution_mode=execution["mode"],
                batch_size=execution["batch_size"],
            )
            coordinator.run(run_id)
            self.store.finish_run(run_id, "completed")
            return self.store.get_run(run_id)
        except Exception as error:
            self.store.finish_run(run_id, "failed", type(error).__name__)
            raise
        finally:
            if writer is not None:
                writer.close()

    def report(self, run_id: str) -> dict[str, Any]:
        from simulation.metrics.report import ReportService
        return ReportService(self.store).run_report(run_id)

    def metric_series(self, run_id: str, metric_name: str, *,
                      scope_type="run", scope_id=None) -> list[dict[str, Any]]:
        from simulation.metrics.report import ReportService
        return ReportService(self.store).metric_series(
            run_id, metric_name, scope_type=scope_type, scope_id=scope_id)

    def agent_history(
        self, run_id: str, agent_id: str, *,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from simulation.metrics.report import ReportService
        return ReportService(self.store).agent_history(
            run_id, agent_id, session_id=session_id
        )

    def rebuild_metrics(self, run_id: str) -> None:
        MetricsProjector(self.store).rebuild(run_id)

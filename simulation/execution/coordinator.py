"""Run orchestration for the new backend snapshot and event store."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

from simulation.decision.stage import StageService
from simulation.metrics.projector import MetricsProjector


class RunCoordinator:
    """Keep stage order per agent and session barriers deterministic."""

    def __init__(
        self, store: Any, stages: StageService, *,
        execution_mode: str = "sequential", batch_size: int = 1,
    ):
        if execution_mode not in {"sequential", "parallel"}:
            raise ValueError("execution_mode must be sequential or parallel")
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.store, self.stages = store, stages
        self.mode, self.batch_size = execution_mode, batch_size
        self.metrics = MetricsProjector(store)
        self.stopped = Event()

    def run(self, run_id: str) -> None:
        snapshot = self.store.run_snapshot(run_id)
        for session in sorted(snapshot["sessions"], key=lambda x: x["session_no"]):
            persisted = self.store.session(session["session_id"])
            if persisted is None or persisted["status"] == "completed":
                continue
            self.store.set_session_status(session["session_id"], "running")
            agents = self._session_agents(snapshot, session)
            if self.mode == "parallel":
                self._parallel_session(run_id, session, agents)
            else:
                for agent in agents:
                    self._run_agent(
                        run_id, session["session_id"], agent["agent_id"],
                        self.stages, self.store,
                    )
            self.metrics.project_session(
                run_id, session["session_id"], complete=True
            )

    @staticmethod
    def _session_agents(snapshot: dict[str, Any], session: dict[str, Any]) -> list[dict]:
        active = session.get("active_agents")
        return [agent for agent in snapshot["agents"]
                if active is None or agent["agent_id"] in active]

    def _parallel_session(self, run_id: str, session: dict[str, Any],
                          agents: list[dict]) -> None:
        def execute(agent: dict[str, Any]) -> None:
            worker_stages = self.stages.clone_for_store(self.store)
            self._run_agent(run_id, session["session_id"], agent["agent_id"],
                            worker_stages, self.store)

        with ThreadPoolExecutor(max_workers=self.batch_size) as pool:
            for start in range(0, len(agents), self.batch_size):
                futures = [pool.submit(execute, agent)
                           for agent in agents[start:start + self.batch_size]]
                for future in futures:
                    future.result()

    def _run_agent(self, run_id: str, session_id: str, agent_id: str,
                   stages: StageService, store: Any) -> None:
        if store.agent_session_status(run_id, session_id, agent_id) == "completed":
            return
        store.agent_session_status(run_id, session_id, agent_id, "running")
        try:
            self._run_posts(run_id, session_id, agent_id, stages, store)
            if not self.stopped.is_set():
                store.agent_session_status(run_id, session_id, agent_id, "completed")
        except Exception:
            self.stopped.set()
            store.agent_session_status(run_id, session_id, agent_id, "failed")
            raise

    def _run_posts(self, run_id, session_id, agent_id, stages, store):
        for post in store.posts(run_id, session_id):
            if self.stopped.is_set():
                return
            encounter = store.encounter(
                run_id, session_id, agent_id, "article", post["post_id"], None
            )
            scope = {
                "run_id": run_id, "session_id": session_id,
                "agent_id": agent_id, "object_type": "article",
                "object_id": post["post_id"],
            }
            attention = self._stage(scope, encounter, "A1", stages)
            if attention["status"] != "resolved":
                continue
            if attention["action"] == "skip":
                self._stage(scope, encounter, "A1R", stages,
                            attention["event_id"])
                continue
            parent = attention["event_id"]
            for stage in ("A2", "A3"):
                result = self._stage(scope, encounter, stage, stages, parent)
                if result["status"] != "resolved":
                    break
                parent = result["event_id"]
            else:
                reaction = self._stage(scope, encounter, "A4", stages, parent)
                if reaction["status"] != "resolved":
                    continue
                visit = self._stage(scope, encounter, "A5", stages,
                                    reaction["event_id"])
                if visit["status"] == "resolved" and visit["action"] in {
                    "visit", "visit_again"
                }:
                    self._run_products(
                        run_id, session_id, agent_id, post["shop_id"],
                        visit["event_id"], stages, store,
                    )

    def _run_products(self, run_id: str, session_id: str, agent_id: str,
                      shop_id: str, parent_event_id: str,
                      stages: StageService, store: Any) -> None:
        for product in store.products(run_id, shop_id):
            encounter = store.encounter(
                run_id, session_id, agent_id, "product", product["product_id"],
                parent_event_id,
            )
            scope = {
                "run_id": run_id, "session_id": session_id,
                "agent_id": agent_id, "object_type": "product",
                "object_id": product["product_id"],
            }
            attention = self._stage(scope, encounter, "B1", stages, parent_event_id)
            if attention["status"] != "resolved":
                continue
            if attention["action"] == "skip":
                self._stage(scope, encounter, "B1R", stages,
                            attention["event_id"])
                continue
            thoughts = self._stage(scope, encounter, "B2", stages,
                                   attention["event_id"])
            if thoughts["status"] == "resolved":
                self._stage(scope, encounter, "B3", stages,
                            thoughts["event_id"])

    def _stage(self, scope: dict[str, str], encounter: int, stage: str,
               stages: StageService, parent_event_id: str | None = None) -> dict:
        if self.stopped.is_set():
            raise RuntimeError("Another agent failed; stop before the next stage")
        return stages.execute(
            run_id=scope["run_id"], session_id=scope["session_id"],
            agent_id=scope["agent_id"], object_type=scope["object_type"],
            object_id=scope["object_id"], encounter_no=encounter, stage=stage,
            context={}, parent_event_id=parent_event_id,
        )

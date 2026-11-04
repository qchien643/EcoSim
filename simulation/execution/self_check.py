"""Offline end-to-end check for the new backend runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from tempfile import TemporaryDirectory
from typing import Any
from pathlib import Path
from copy import deepcopy

from backend.runtime import BackendRunExecutor
from backend.self_check import fixture
from backend.store import BackendStore
from simulation.decision.stage import GatewayResponse
from simulation.personas.bundle import load_bundle


def _levels(level: int) -> list[float]:
    return [1.0 if index == level else 0.0 for index in range(4)]


@dataclass
class ScriptedGateway:
    provider: str = "offline"
    model: str = "scripted"
    calls: list[str] = field(default_factory=list)

    def decide(self, stage: str, context: dict[str, Any]) -> GatewayResponse:
        self.calls.append(stage)
        if stage in {"A1", "B1"}:
            output = {"probabilities": _levels(3)}
        elif stage in {"A2", "A3", "B2", "A1R", "B1R"}:
            output = {"distributions": {
                tag: _levels(3) for tag in
                context["rendered"]["answer_map"].values()
            }}
        elif stage == "A4":
            output = {"answer": (
                "like" if context["history"]["current_reaction"] is None
                else "keep_current"
            )}
        elif stage == "A5":
            output = {"answer": (
                "visit" if context["history"]["shop_visit_count"] == 0
                else "visit_again"
            )}
        elif stage == "B3":
            output = {"answer": (
                "not_buy" if context["history"]["purchase_count"] == 0
                else "not_buy_again"
            )}
        else:
            raise AssertionError(stage)
        return GatewayResponse(
            output={**output, "source": "jev"},
            provider=self.provider, model=self.model,
            request={"stage": stage, "context": context},
        )


def _prepare(store: BackendStore, *, repeat_post: bool = False,
             agent_count: int = 2, mode: str = "sequential", batch_size: int = 1,
             multi_product: bool = False, inactive_first: bool = False) -> None:
    store.register_dataset(
        dataset_id="dataset_runtime", source_name="runtime fixture",
        revision="1", source_uri="managed://runtime", schema_hash="test",
        manifest={"rows": agent_count}, usage_notice="offline fixture",
    )
    store.register_industry(
        industry_id="cafe", profile_version="cafe-mvp-v1",
        bundle=load_bundle("cafe", "cafe-mvp-v1"),
    )
    store.register_cohort(
        cohort_id="cohort_cafe_2", dataset_id="dataset_runtime",
        industry_id="cafe", profile_version="cafe-mvp-v1",
        selection_policy={"seed": 1},
        members=[{
            "cohort_persona_id": f"cafe_{i:03}", "source_persona_id": f"source_{i:03}",
            "persona": {"trait_curiosity": "Strong"}, "provenance": {},
            "field_provenance": {},
        } for i in range(1, agent_count + 1)],
    )
    campaign = store.create_campaign({
        "campaign_id": "campaign_runtime", "name": "Runtime fixture",
        "brief": "Offline execution.",
    })
    scenario_input = fixture()
    scenario_input["agent_count"] = agent_count
    if multi_product:
        second = deepcopy(scenario_input["products"][0])
        second.update(product_id="product_second", position=2)
        scenario_input["products"].append(second)
    if inactive_first:
        scenario_input["sessions"][0]["active_agent_ids"] = [
            f"agent_cafe_{i:03}" for i in range(2, agent_count + 1)
        ]
    if repeat_post:
        scenario_input["sessions"][1]["posts"] = [
            {"post_id": "post_demo", "position": 1}
        ]
    scenario = store.create_scenario(campaign["campaign_id"], scenario_input)
    store.freeze_scenario(scenario["scenario_id"], 1)
    store.create_run(
        scenario["scenario_id"], {"mode": mode, "batch_size": batch_size},
        "run_runtime", "runtime-create",
    )


def main() -> None:
    with TemporaryDirectory(prefix="ecosim-new-runtime-") as directory:
        store = BackendStore(Path(directory) / "backend.sqlite")
        try:
            _prepare(store)
            gateway = ScriptedGateway()
            result = BackendRunExecutor(store).execute(
                "run_runtime", primary=gateway
            )
            assert result["status"] == "completed"
            assert store.run_status("run_runtime") == "completed"
            assert store.connection.execute(
                "SELECT COUNT(*) FROM stage_events WHERE run_id=?",
                ("run_runtime",),
            ).fetchone()[0] > 0
            report = BackendRunExecutor(store).report("run_runtime")
            assert report["sessions"]
            history = BackendRunExecutor(store).agent_history(
                "run_runtime", "agent_cafe_001"
            )
            assert history and history[0]["stage"] == "A1"
            assert {event["stage"] for event in history} == {
                "A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3"
            }, history
            assert all(event["status"] == "resolved" for event in history)
            assert store.progress("run_runtime")["sessions_completed"] == 2
            print("PASS: new backend runtime writes events, metrics and history")
        finally:
            store.close()


if __name__ == "__main__":
    main()

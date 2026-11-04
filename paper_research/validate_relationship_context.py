"""Offline integration checks for relationship-aware context rendering."""

from pathlib import Path
from tempfile import TemporaryDirectory

from simulation.personas.assignment import default_relationship
from simulation.personas.relationship import transition_relationship, validate_policy
from simulation.self_check import ScriptedGateway, example_scenario
from simulation.context.service import ContextService
from simulation.orchestrator import RunCoordinator
from simulation.setup.loader import ScenarioLoader
from simulation.decision.stage import StageService
from simulation.store_sqlite import SqliteSimulationStore


def main() -> None:
    validate_policy()
    state = default_relationship()
    state = transition_relationship(
        state,
        {"stage": "A3", "status": "resolved",
         "brand_identity_visible": True},
    )
    assert state == {
        "awareness": "aware",
        "familiarity": "low",
        "attitude": "not_formed",
        "purchase_history": "none",
    }
    state = transition_relationship(
        state, {"stage": "A5", "action": "visit"}
    )
    assert state["familiarity"] == "established"
    unchanged = transition_relationship(
        state, {"stage": "A4", "action": "dislike"}
    )
    assert unchanged == state
    state = transition_relationship(
        state, {"stage": "B3", "action": "buy"}
    )
    assert state["purchase_history"] == "has_purchased"

    scenario = example_scenario()
    scenario["relationship_initialization"] = {
        "seed": 11,
        "groups": [{
            "group_id": "unknown",
            "state": default_relationship(),
            "count": 1,
        }],
    }
    loaded = ScenarioLoader().load(scenario)
    gateway = ScriptedGateway()
    with TemporaryDirectory(prefix="projectdut-relationship-context-") as directory:
        store = SqliteSimulationStore(Path(directory) / "run.sqlite")
        RunCoordinator(store, StageService(store, gateway)).run(loaded)
        a1_contexts = [
            context for stage, context in gateway.calls if stage == "A1"
        ]
        assert len(a1_contexts) == 2
        first, second = a1_contexts
        assert first["input"]["relationship_state"] == {
            "awareness": "unknown",
            "familiarity": "none",
            "attitude": "not_formed",
            "purchase_history": "none",
        }
        assert "brand_history" not in first["input"]
        assert first["input"]["article_memory_summary"]["prior_exposure_count"] == 0
        assert "No prior awareness of this brand is recorded." in first["state"]
        assert "relationship_state" not in first["state"]
        assert second["input"]["relationship_state"] == {
            "awareness": "aware",
            "familiarity": "established",
            "attitude": "not_formed",
            "purchase_history": "none",
        }
        assert second["input"]["article_memory_summary"]["prior_exposure_count"] == 1
        assert second["input"]["article_memory_summary"]["prior_read_count"] == 1
        current = store.relationship(
            loaded["run_id"], "agent_1",
            loaded["organization_id"], loaded["brand_id"],
        )
        assert current["initial_state"] == default_relationship()
        assert current["state"]["familiarity"] == "established"
        assert current["state"]["purchase_history"] == "none"
        store.close()
    print("PASS: deterministic relationship transitions and no implicit attitude change")
    print("PASS: relationship state and brand history are stage-filtered in context")
    print("PASS: current relationship projection is persisted separately from initial state")


if __name__ == "__main__":
    main()

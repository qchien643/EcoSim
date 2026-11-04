"""Offline checks for cohort-backed scenario materialization."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from simulation.setup.loader import ScenarioLoader
from simulation.setup.materializer import ScenarioMaterializationError
from simulation.self_check import ScriptedGateway
from simulation.decision.stage import StageService
from simulation.store_sqlite import SqliteSimulationStore


ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "data/scenarios/cafe_mvp/scenario-draft.json"


def main() -> None:
    loader = ScenarioLoader()
    draft = loader._read(DRAFT)
    original = deepcopy(draft)
    scenario = loader.load(draft)
    assert draft == original
    assert len(scenario["agents"]) == 100
    assert len(scenario["relationship_assignments"]) == 100
    assert scenario["persona_cohort_snapshot"]["selected_size"] == 100
    assert scenario["customer_structure"]["total_agents"] == 100
    members = [
        agent_id
        for group in scenario["customer_structure"]["groups"]
        for agent_id in group["agent_ids"]
    ]
    assert len(members) == 100
    assert len(set(members)) == 100
    assert set(members) == {agent["agent_id"] for agent in scenario["agents"]}
    assert len(scenario["sessions"]) == 2
    assert len(scenario["products"]) == 2

    reloaded = loader.load(scenario)
    assert reloaded == scenario

    tampered = deepcopy(scenario)
    tampered["persona_cohort_snapshot"]["cohort_sha256"] = "changed"
    try:
        loader.load(tampered)
    except ScenarioMaterializationError:
        pass
    else:
        raise AssertionError("Cohort snapshot drift was accepted")

    with TemporaryDirectory(prefix="projectdut-materialized-") as directory:
        store = SqliteSimulationStore(Path(directory) / "scenario.sqlite")
        from simulation.orchestrator import RunCoordinator

        RunCoordinator(
            store, StageService(store, ScriptedGateway())
        ).load_scenario(scenario)
        assert len(store.agents(scenario["run_id"])) == 100
        assert len(store.relationships(scenario["run_id"])) == 100
        stored = store.run_snapshot(scenario["run_id"])
        assert stored == scenario
        store.close()
        reopened = SqliteSimulationStore(Path(directory) / "scenario.sqlite")
        assert reopened.run_snapshot(scenario["run_id"]) == scenario
        assert len(reopened.relationships(scenario["run_id"])) == 100
        reopened.close()

    print("PASS: cohort, persona, customer structure and relationship materialization")
    print("PASS: deterministic reload and cohort snapshot drift rejection")
    print("PASS: complete scenario snapshot persisted and reopened from SQLite")


if __name__ == "__main__":
    main()

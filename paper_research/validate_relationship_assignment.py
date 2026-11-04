"""Offline checks for Phase 4 relationship state and deterministic assignment."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from simulation.personas.assignment import (
    RelationshipAssignmentError,
    assign_relationships,
    default_relationship,
    materialize_relationships,
    validate_initialization,
    validate_relationship_state,
)
from simulation.setup.loader import ScenarioLoader
from simulation.orchestrator import RunCoordinator
from simulation.self_check import ScriptedGateway, example_scenario
from simulation.decision.stage import StageService
from simulation.store_sqlite import SqliteSimulationStore


def main() -> None:
    agents = [{"agent_id": f"agent_{index}"} for index in range(1, 11)]
    initialization = {
        "seed": 20260928,
        "groups": [
            {
                "group_id": "unknown",
                "state": default_relationship(),
                "percentage": 40,
            },
            {
                "group_id": "known_positive",
                "state": {
                    "awareness": "aware",
                    "familiarity": "established",
                    "attitude": "positive",
                    "purchase_history": "none",
                },
                "percentage": 60,
            },
        ],
    }
    assert not validate_initialization(
        initialization, [agent["agent_id"] for agent in agents]
    )
    first = assign_relationships(
        agents, initialization, organization_id="org", brand_id="brand"
    )
    second = assign_relationships(
        agents, deepcopy(initialization), organization_id="org", brand_id="brand"
    )
    assert first == second
    assert [item["group_id"] for item in first].count("unknown") == 4
    assert [item["group_id"] for item in first].count("known_positive") == 6
    assert {item["agent_id"] for item in first} == {
        agent["agent_id"] for agent in agents
    }

    assert validate_relationship_state({
        "awareness": "unknown",
        "familiarity": "established",
        "attitude": "positive",
        "purchase_history": "none",
    })
    assert validate_relationship_state({
        "awareness": "aware",
        "familiarity": "none",
        "attitude": "not_formed",
        "purchase_history": "has_purchased",
    })
    assert validate_initialization({
        "seed": 1,
        "groups": [{
            "group_id": "bad", "state": default_relationship(),
            "percentage": 100,
        }],
    }, ["agent_1"]) == []
    invalid = deepcopy(initialization)
    invalid["groups"][0]["state"]["awareness"] = "unknown"
    invalid["groups"][0]["state"]["attitude"] = "positive"
    assert validate_initialization(invalid, ["agent_1"])
    invalid_mode = deepcopy(initialization)
    invalid_mode["groups"][0]["count"] = 4
    assert validate_initialization(invalid_mode, [agent["agent_id"] for agent in agents])

    scenario = example_scenario()
    scenario["relationship_initialization"] = {
        "seed": 7,
        "groups": [{
            "group_id": "unknown",
            "state": default_relationship(),
            "count": 1,
        }],
    }
    loaded = ScenarioLoader().load(scenario)
    assert loaded["relationship_assignments"][0]["state"] == default_relationship()
    assert loaded["relationship_assignments"][0]["brand_id"] == scenario["brand_id"]
    assert materialize_relationships(loaded) == loaded["relationship_assignments"]
    conflicting = deepcopy(loaded)
    conflicting["relationship_assignments"][0:0] = [{
        "agent_id": "agent_1",
        "organization_id": scenario["organization_id"],
        "brand_id": scenario["brand_id"],
        "group_id": "unknown",
        "state": default_relationship(),
        "provenance": {},
    }]
    try:
        ScenarioLoader().load(conflicting)
    except (RelationshipAssignmentError, ValueError):
        pass
    else:
        raise AssertionError("Conflicting supplied assignments were accepted")
    with TemporaryDirectory(prefix="projectdut-relationship-") as directory:
        store = SqliteSimulationStore(Path(directory) / "relationship.sqlite")
        RunCoordinator(
            store, StageService(store, ScriptedGateway())
        ).run(loaded)
        persisted = store.relationship(
            loaded["run_id"], "agent_1",
            loaded["organization_id"], loaded["brand_id"],
        )
        assert persisted is not None
        assert persisted["initial_state"] == default_relationship()
        assert persisted["state"]["awareness"] == "aware"
        assert persisted["state"]["familiarity"] == "established"
        assert len(store.relationships(loaded["run_id"])) == 1
        store.close()
    print("PASS: relationship state enums and compatibility rules")
    print("PASS: count/percentage allocation, stable seed and full agent partition")
    print("PASS: loader materializes and rejects relationship assignment drift")


if __name__ == "__main__":
    main()

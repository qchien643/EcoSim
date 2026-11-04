"""Audit actual stage contexts against visibility and scope rules."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from simulation.orchestrator import RunCoordinator
from simulation.setup.loader import ScenarioLoader
from simulation.self_check import ScriptedGateway
from simulation.decision.stage import StageService
from simulation.store_sqlite import SqliteSimulationStore

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "data/scenarios/cafe_mvp/scenario-draft.json"
ARTICLE_TEXT = (
    "The cafe introduces an iced orange coffee with a lightly sweet citrus "
    "profile for customers who want to try something new."
)
PRODUCT_DESCRIPTION = "Iced coffee with a lightly sweet orange profile."


def _scenario_one_agent() -> dict:
    scenario = ScenarioLoader()._read(DRAFT)
    scenario["run_id"] = "run_context_audit"
    scenario["scenario_id"] = "scenario_context_audit"
    scenario["persona_cohort"]["agent_count"] = 1
    scenario["customer_structure"]["total_agents"] = 1
    scenario["customer_structure"]["groups"] = [
        {"group_id": "all_agents", "percentage": 100}
    ]
    return scenario


def _calls(gateway, stage):
    return [context for current, context in gateway.calls if current == stage]


def main() -> None:
    scenario = ScenarioLoader().load(_scenario_one_agent())
    gateway = ScriptedGateway()
    with TemporaryDirectory(prefix="projectdut-context-audit-") as directory:
        store = SqliteSimulationStore(Path(directory) / "audit.sqlite")
        RunCoordinator(store, StageService(store, gateway)).run(scenario)

        first_a1, second_a1 = _calls(gateway, "A1")
        first_b1, second_b1 = _calls(gateway, "B1")[:2]
        a3 = _calls(gateway, "A3")[0]
        a4 = _calls(gateway, "A4")[0]
        a5 = _calls(gateway, "A5")[0]
        b2 = _calls(gateway, "B2")[0]
        b3 = _calls(gateway, "B3")[0]

        # The actual network state is rendered text; internal context keys are
        # retained only in the audit record passed to model_calls.
        for stage, context in gateway.calls:
            assert context["input"]["scope"]["agent_id"] == scenario["agents"][0]["agent_id"]
            assert context["input"]["scope"]["run_id"] == scenario["run_id"]
            assert "relationship_state" not in context["state"]
            assert "brand_history" not in context["state"]
            for forbidden in (
                "cafe_post_orange_coffee",
                "cafe_product_orange_coffee",
                "agent_",
                "trait_curiosity",
                "purchase_history",
                "previous_same_stage_state",
            ):
                assert forbidden not in context["state"], (stage, forbidden)

        # First and second attention contexts receive accumulated brand
        # evidence only from encounters before the current encounter.
        assert "brand_history" not in first_a1["input"]
        assert first_a1["input"]["article_memory_summary"]["prior_exposure_count"] == 0
        assert second_a1["input"]["article_memory_summary"]["prior_exposure_count"] == 1
        assert second_a1["input"]["article_memory_summary"]["prior_read_count"] == 1
        assert first_a1["input"]["relationship_state"]["awareness"] == "unknown"
        assert second_a1["input"]["relationship_state"]["awareness"] == "aware"

        # Article content is available only after attention, at A3.
        assert ARTICLE_TEXT not in first_a1["state"]
        assert ARTICLE_TEXT not in _calls(gateway, "A2")[0]["state"]
        assert ARTICLE_TEXT in a3["state"]
        assert ARTICLE_TEXT not in a4["state"]
        assert ARTICLE_TEXT not in a5["state"]

        # Product detail boundary: B1 has name/price but not description;
        # B2/B3 receive the description.
        assert "Iced orange coffee" in first_b1["state"]
        assert "39,000 VND" in first_b1["state"]
        assert PRODUCT_DESCRIPTION not in first_b1["state"]
        assert PRODUCT_DESCRIPTION in b2["state"]
        assert PRODUCT_DESCRIPTION in b3["state"]

        # Current upstream memory is exact and scoped.
        assert a4["input"]["current_state"]["stage"] == "A3"
        assert a5["input"]["current_state"]["stage"] == "A3"
        assert b3["input"]["current_state"]["stage"] == "B2"
        assert a4["input"]["current_state"]["object_id"] == \
            a4["input"]["scope"]["object_id"]
        assert b3["input"]["current_state"]["object_id"] == \
            b3["input"]["scope"]["object_id"]

        # Persona is present only at stages whose mapping permits it.
        assert first_a1["input"]["persona"]
        assert _calls(gateway, "A2")[0]["input"]["persona"]
        assert first_b1["input"]["persona"]
        assert b2["input"]["persona"]
        for context in (a3, a4, a5, b3):
            assert "persona" not in context["input"]

        # B3 receives product-local history separately from brand relationship.
        assert b3["input"]["history"]["purchase_count"] == 0
        assert "brand_history" not in b3["input"]
        store.close()
    print("PASS: actual prompts do not expose internal IDs or relationship keys")
    print("PASS: article/product visibility boundaries hold across both sessions")
    print("PASS: scoped upstream state, persona mapping and history are correct")


if __name__ == "__main__":
    main()

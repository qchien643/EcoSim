"""Offline check: python3 -m paper_research.validate_industry_profiles."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from simulation.personas.industry_profile import IndustryProfileError, load_profile, validate_profile
from simulation.setup.loader import ScenarioLoader
from simulation.setup.validator import ScenarioValidationError
from simulation.self_check import example_scenario, ScriptedGateway
from simulation.orchestrator import RunCoordinator
from simulation.decision.stage import StageService
from simulation.store_sqlite import SqliteSimulationStore


def rejected(call, error_type=IndustryProfileError):
    try:
        call()
    except error_type:
        return
    raise AssertionError("Invalid input was accepted")


def main():
    profile = load_profile("cafe", "cafe-mvp-v1")
    assert len(profile["core_persona_fields"]) == 12
    assert len(profile["domain_persona_fields"]) == 5
    for industry, version in [
        ("../cafe", "cafe-mvp-v1"), ("cafe", "../cafe-mvp-v1"),
        ("/tmp", "cafe-mvp-v1"), ("cafe", ""), (None, []),
        ("missing", "missing-v1"),
    ]:
        rejected(lambda: load_profile(industry, version))
    rejected(lambda: validate_profile(None))
    rejected(lambda: validate_profile(profile, expected_industry="other"))
    rejected(lambda: validate_profile(profile, expected_version="other-v1"))
    mutations = [
        ("core_persona_fields", ["missing_field"]),
        ("domain_persona_fields", ["trait_curiosity"]),
        ("domain_persona_fields", []),
        ("grouping_fields", [{}]),
        ("core_persona_fields", ["trait_curiosity", "trait_curiosity"]),
        ("stage_base_fields", {"A3": ["trait_curiosity"]}),
        ("stage_base_fields", {"A1": [{}]}),
        ("tag_registry", {"path": "../../../../.env", "version": "2.0-draft"}),
        ("persona_mapping", {**profile["persona_mapping"], "version": "unknown"}),
    ]
    for field, value in mutations:
        bad = {**deepcopy(profile), field: value}
        rejected(lambda: validate_profile(bad))

    loader = ScenarioLoader()
    scenario = example_scenario()
    original = deepcopy(scenario)
    frozen = loader.load(scenario)
    assert scenario == original and loader.load(frozen) == frozen
    assert frozen["industry_profile_snapshot"]["profile"] == profile
    for field in ("industry_id", "industry_profile_version"):
        bad = deepcopy(scenario)
        del bad[field]
        rejected(lambda: loader.load(bad), ScenarioValidationError)
    for persona in ({"topic_coffee": "Invented"}, {"cog_verbosity": "Concise"},
                    {"trait_curiosity": []}):
        bad = deepcopy(scenario)
        bad["agents"][0]["persona"] = persona
        rejected(lambda: loader.load(bad), ScenarioValidationError)

    sparse = deepcopy(scenario)
    sparse["agents"][0]["persona"] = {
        "trait_curiosity": None, "lstyle_caffeine": "None", "region": "Southeast Asia",
    }
    assert loader.load(sparse)["agents"] == sparse["agents"]
    tampered = deepcopy(frozen)
    tampered["industry_profile_snapshot"]["asset_hashes"]["tag_registry"] = "changed"
    rejected(lambda: loader.load(tampered), ScenarioValidationError)
    changed = deepcopy(profile)
    changed["notes"].append("Changed profile under the same version.")
    with patch("simulation.setup.validator.load_profile", return_value=changed):
        rejected(lambda: loader.load(frozen), ScenarioValidationError)

    with TemporaryDirectory(prefix="projectdut-industry-") as directory:
        path = Path(directory) / "run.sqlite"
        store = SqliteSimulationStore(path)
        gateway = ScriptedGateway()
        RunCoordinator(store, StageService(store, gateway)).run(sparse)
        assert all("Southeast Asia" not in context["state"]
                   and "Reported value: None." in context["state"]
                   for stage, context in gateway.calls if stage == "B2")
        persisted = store.run_snapshot(sparse["run_id"])
        store.close()
        store = SqliteSimulationStore(path)
        assert store.run_snapshot(sparse["run_id"]) == persisted
        assert loader.load(persisted) == persisted
        store.close()
    print("PASS: profile fields, references, stage baselines, versions and path boundaries")
    print("PASS: missing/invalid industry, persona enums, sparse fields and grouping isolation")
    print("PASS: immutable profile snapshot, drift rejection, SQLite persistence and reopen")


if __name__ == "__main__":
    main()

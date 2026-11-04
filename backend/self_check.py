"""Offline check for the backend v1 persistence slice."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy

from .store import BackendConflictError, BackendStore, BackendValidationError
from simulation.personas.bundle import load_bundle


def fixture() -> dict:
    return {
        "name": "Demo scenario",
        "cohort_id": "cohort_cafe_2",
        "industry_id": "cafe",
        "profile_version": "cafe-mvp-v1",
        "policy_version": "simulation-policy-v1",
        "agent_count": 2,
        "selection_seed": 7,
        "assignment_seed": 8,
        "business": {
            "organization_id": "org_demo",
            "organization_name": "Demo Coffee",
            "organization_description": "A local coffee business.",
            "brand_id": "brand_demo",
            "brand_name": "Demo Coffee",
            "brand_description": "Everyday coffee and seasonal drinks.",
            "tags": [],
        },
        "shops": [{
            "shop_id": "shop_demo",
            "name": "Demo shop",
            "public_profile": "A neighborhood coffee shop.",
            "tags": [],
        }],
        "posts": [{
            "post_id": "post_demo",
            "shop_id": "shop_demo",
            "title": "New drink",
            "preview": "A new cold coffee.",
            "article_content": "A new cold coffee for an afternoon break.",
            "tags": [],
        }],
        "products": [{
            "product_id": "product_demo",
            "shop_id": "shop_demo",
            "position": 1,
            "product_name": "Cold coffee",
            "listed_price": "39000 VND",
            "product_description": "Cold coffee with a light citrus note.",
            "tags": [],
        }],
        "sessions": [
            {"session_no": 1, "posts": [{"post_id": "post_demo", "position": 1}]},
            {"session_no": 2, "posts": []},
        ],
        "relationship_groups": [{
            "group_id": "unknown",
            "percentage": 100,
            "state": {
                "awareness": "unknown",
                "familiarity": "none",
                "attitude": "not_formed",
                "purchase_history": "none",
            },
        }],
    }


def main() -> None:
    with TemporaryDirectory(prefix="ecosim-backend-") as directory:
        store = BackendStore(Path(directory) / "backend.sqlite")
        try:
            store.register_dataset(
                dataset_id="dataset_matraix_v2",
                source_name="MatrAIx Persona 1M",
                revision="2026-09-02",
                source_uri="managed://matraix/persona-1m",
                schema_hash="schema-hash",
                manifest={"rows": 2},
                usage_notice="Research-only source; verify rights before commercial use.",
            )
            store.register_industry(
                industry_id="cafe",
                profile_version="cafe-mvp-v1",
                bundle=load_bundle("cafe", "cafe-mvp-v1"),
            )
            store.register_cohort(
                cohort_id="cohort_cafe_2",
                dataset_id="dataset_matraix_v2",
                industry_id="cafe",
                profile_version="cafe-mvp-v1",
                selection_policy={"seed": 1},
                members=[
                    {
                        "cohort_persona_id": "cafe_001",
                        "source_persona_id": "source_001",
                        "persona": {"trait_curiosity": "Moderate"},
                        "provenance": {"source": "synthetic"},
                        "field_provenance": {"trait_curiosity": {"status": "observed"}},
                        "cohort_bucket": "synthetic",
                    },
                    {
                        "cohort_persona_id": "cafe_002",
                        "source_persona_id": "source_002",
                        "persona": {"trait_curiosity": "Strong"},
                        "provenance": {"source": "synthetic"},
                        "field_provenance": {"trait_curiosity": {"status": "observed"}},
                        "cohort_bucket": "synthetic",
                    },
                ],
            )
            campaign = store.create_campaign({
                "campaign_id": "campaign_demo",
                "name": "Demo campaign",
                "brief": "Introduce a seasonal drink.",
            })
            scenario = store.create_scenario(campaign["campaign_id"], fixture())
            report = store.validate_scenario(scenario["scenario_id"])
            assert report["valid"] is True, report
            invalid = deepcopy(fixture())
            invalid["business"]["tags"] = [{
                "tag_id": "enterprise.local_business",
                "source_ref": "brand:brand_demo:brand_name",
                "visible_stages": ["A1"],
            }]
            invalid["posts"][0]["tags"] = [{
                "tag_id": "article.product_focus",
                "source_ref": "post:post_demo:title",
                "visible_stages": ["A1"],
            }]
            invalid_campaign = store.create_campaign({
                "campaign_id": "campaign_invalid_tags",
                "name": "Invalid tag fixture",
                "brief": "Validation only.",
            })
            invalid_scenario = store.create_scenario(
                invalid_campaign["campaign_id"], invalid,
            )
            invalid_report = store.validate_scenario(
                invalid_scenario["scenario_id"]
            )
            assert not invalid_report["valid"]
            assert any(
                issue["code"] == "TAG_SOURCE_REF"
                for issue in invalid_report["issues"]
            )
            assert any(
                issue["code"] == "TAG_SOURCE_REF"
                and issue["path"].startswith("setup.posts[0].tags")
                for issue in invalid_report["issues"]
            )
            frozen = store.freeze_scenario(scenario["scenario_id"], 1)
            assert frozen["status"] == "ready"
            run = store.create_run(
                scenario["scenario_id"],
                {"mode": "parallel", "batch_size": 2},
                "run_demo",
                "create-run-demo",
            )
            assert run["status"] == "ready"
            assert len(run["sessions"]) == 2
            assert store.get_run("run_demo")["input_snapshot"]["setup"]["selected_members"]
            replay = store.create_run(
                scenario["scenario_id"],
                {"mode": "parallel", "batch_size": 2},
                "run_demo",
                "create-run-demo",
            )
            assert replay["run_id"] == "run_demo"
            try:
                store.create_run(
                    scenario["scenario_id"],
                    {"mode": "sequential", "batch_size": 1},
                    "run_other",
                    "create-run-demo",
                )
            except BackendConflictError:
                pass
            else:
                raise AssertionError("idempotency key accepted a different request")
            try:
                store.create_run(
                    scenario["scenario_id"],
                    {"mode": "parallel", "batch_size": 2},
                    "run_revision_conflict",
                    "create-run-revision",
                    expected_revision=2,
                )
            except BackendConflictError:
                pass
            else:
                raise AssertionError("stale scenario revision was accepted")
            try:
                store.replace_scenario(scenario["scenario_id"], fixture(), 1)
            except Exception:
                pass
            else:
                raise AssertionError("ready scenario was editable")

            draft_campaign = store.create_campaign({
                "campaign_id": "campaign_draft",
                "name": "Draft campaign",
                "brief": "Draft only.",
            })
            draft = store.create_scenario(
                draft_campaign["campaign_id"],
                fixture(),
            )
            try:
                store.create_run(
                    draft["scenario_id"],
                    {"mode": "sequential", "batch_size": 1},
                )
            except BackendConflictError:
                pass
            else:
                raise AssertionError("unfrozen scenario created a run")
            print("PASS: backend v1 dataset/cohort, scenario freeze and atomic run snapshot")
        finally:
            store.close()


if __name__ == "__main__":
    main()

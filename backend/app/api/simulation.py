"""
Simulation API — MiroFish-style 5-step prepare + run + manage.

E2E Flow:
  Phase 3: API → Parquet(ProfileGen) + KG(SimConfigGen) → merge
  Phase 4: API → SR → subprocess(run_simulation.py) → actions.jsonl
"""

import json
import logging
import os

from flask import Blueprint, jsonify, request

from ..config import Config
from ..models.simulation import SimStatus
from ..services.profile_generator import ProfileGenerator
from ..services.sim_config_generator import SimConfigGenerator
from ..services.crisis_injector import CrisisInjector
from ..services.sim_manager import SimManager
from ..services.graph_query import GraphQuery

logger = logging.getLogger("ecosim.api.simulation")

simulation_bp = Blueprint("simulation", __name__, url_prefix="/api/sim")

sim_manager = SimManager()


@simulation_bp.route("/prepare", methods=["POST"])
def prepare_simulation():
    """Prepare simulation — MiroFish-style 5-step pipeline.

    Request JSON:
        campaign_id: str (required)
        num_agents: int (default 10)
        num_rounds: int (default 24, custom mode override)

    Response: profiles + time_config + event_config + rec_config + reasoning
    """
    data = request.get_json() or {}
    campaign_id = data.get("campaign_id", "")
    num_agents = data.get("num_agents", 10)
    num_rounds = data.get("num_rounds", 24)
    cognitive_toggles = data.get("cognitive_toggles", {
        "enable_agent_memory": True,
        "enable_mbti_modifiers": True,
        "enable_interest_drift": True,
        "enable_reflection": True,
        "enable_graph_cognition": False,
    })

    if not campaign_id:
        return jsonify({"error": "campaign_id is required"}), 400

    # Verify campaign exists
    spec_path = os.path.join(Config.UPLOAD_DIR, f"{campaign_id}_spec.json")
    if not os.path.exists(spec_path):
        return jsonify({"error": f"Campaign {campaign_id} not found"}), 404

    try:
        # Create simulation
        state = sim_manager.create(campaign_id, num_agents)
        state.total_rounds = num_rounds
        sim_manager.update_status(state.sim_id, SimStatus.PREPARING)

        # Load campaign context
        with open(spec_path, "r", encoding="utf-8") as f:
            spec = json.load(f)
        campaign_context = (
            f"Campaign: {spec.get('name', '')}\n"
            f"Type: {spec.get('campaign_type', '')}\n"
            f"Market: {spec.get('market', '')}\n"
            f"Summary: {spec.get('summary', '')}"
        )

        # ── Step 01: Get KG entities (for SimConfig, not profiles) ──
        logger.info("Step 01: Loading KG entities for sim config...")
        entities = []
        try:
            gq = GraphQuery()
            entities = gq.get_all_entities(limit=100)
            logger.info(f"Found {len(entities)} KG entities")
        except Exception as e:
            logger.warning(f"KG entity loading failed (non-fatal for profiles): {e}")

        # ── Step 02 + 03-04: Profile Gen (Parquet) & SimConfig Gen (PARALLEL) ──
        logger.info(f"Step 02+03: Generating {num_agents} profiles + sim config in parallel...")
        pg = ProfileGenerator()
        warnings = []
        time_config = None
        event_config = None
        rec_config = None
        config_result = None

        from concurrent.futures import ThreadPoolExecutor

        def gen_profiles():
            return pg.generate(campaign_id, num_agents, campaign_context)

        def gen_sim_config():
            scg = SimConfigGenerator()
            return scg.generate(
                campaign_context=campaign_context,
                entities=entities,
                num_agents=num_agents,
                custom_rounds=num_rounds,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_profiles = executor.submit(gen_profiles)
            future_config = executor.submit(gen_sim_config)

            # Wait for profiles
            profiles = future_profiles.result()

            # Wait for sim config (non-fatal if fails)
            try:
                config_result = future_config.result()
                time_config = config_result["time_config"]
                event_config = config_result["event_config"]
                rec_config = config_result["rec_config"]
            except Exception as e:
                logger.warning(f"Step 03-04 failed (non-fatal): {e}", exc_info=True)
                warnings.append(f"SimConfig generation failed: {str(e)[:100]}")

        # ── Save profiles (OASIS Reddit JSON format) ──
        profiles_json_path = os.path.join(state.output_dir, "profiles.json")
        pg.save_json(profiles, profiles_json_path)
        state.profiles_path = profiles_json_path

        # Release DuckDB connection
        pg.close()

        # ── Save sim config (if generated) ──
        config_reasoning = ""
        config_estimated = 0
        if time_config and event_config and rec_config:
            sim_config = {
                "sim_id": state.sim_id,
                "campaign_id": campaign_id,
                "num_agents": num_agents,
                "time_config": time_config.model_dump(),
                "event_config": event_config.model_dump(),
                "rec_config": rec_config.model_dump(),
                "cognitive_toggles": cognitive_toggles,
                "reasoning": config_result.get("reasoning", ""),
                "estimated_duration_minutes": config_result.get("estimated_duration_minutes", 0),
            }
            config_path = os.path.join(state.output_dir, "sim_config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(sim_config, f, indent=2, ensure_ascii=False)
            state.config_path = config_path
            config_reasoning = config_result.get("reasoning", "")
            config_estimated = config_result.get("estimated_duration_minutes", 0)

        # ── Step 05: Crisis scenarios ──
        scenarios = []
        try:
            logger.info("Step 05: Generating crisis scenarios...")
            ci = CrisisInjector()
            scenarios = ci.generate_scenarios(
                "", campaign_id=campaign_id,
                total_rounds=num_rounds,
            )
            crisis_path = os.path.join(state.output_dir, "crisis_scenarios.json")
            ci.save_scenarios(scenarios, crisis_path)
            state.crisis_path = crisis_path
        except Exception as e:
            logger.warning(f"Step 05 failed (non-fatal): {e}", exc_info=True)
            warnings.append(f"Crisis generation failed: {str(e)[:100]}")

        # Update total_rounds
        if time_config:
            state.total_rounds = time_config.total_rounds

        # Update status
        sim_manager.update_status(state.sim_id, SimStatus.READY)

        # ── Build response ──
        response = {
            "sim_id": state.sim_id,
            "status": "ready",
            "profiles": {
                "count": len(profiles),
                "path": profiles_path,
                "sample": [p.model_dump() for p in profiles],
            },
            "time_config": time_config.model_dump() if time_config else None,
            "rec_config": rec_config.model_dump() if rec_config else None,
            "event_config": event_config.model_dump() if event_config else None,
            "crisis_scenarios": {
                "count": len(scenarios),
                "path": state.crisis_path,
                "names": [s.name for s in scenarios] if scenarios else [],
            },
            "reasoning": config_reasoning,
            "estimated_duration_minutes": config_estimated,
        }

        if warnings:
            response["warnings"] = warnings

        return jsonify(response), 201

    except Exception as e:
        logger.error(f"Prepare failed: {e}", exc_info=True)
        if 'state' in locals():
            sim_manager.update_status(state.sim_id, SimStatus.FAILED, str(e))
        return jsonify({"error": str(e)}), 500


@simulation_bp.route("/status", methods=["GET"])
def get_status():
    """Get simulation status."""
    sim_id = request.args.get("sim_id", "")
    if not sim_id:
        return jsonify({"error": "sim_id is required"}), 400

    state = sim_manager.get(sim_id)
    if not state:
        return jsonify({"error": f"Simulation {sim_id} not found"}), 404

    return jsonify({
        "sim_id": state.sim_id,
        "status": state.status.value,
        "campaign_id": state.campaign_id,
        "num_agents": state.num_agents,
        "current_round": state.current_round,
        "total_rounds": state.total_rounds,
        "profiles_path": state.profiles_path,
        "crisis_path": state.crisis_path,
        "error": state.error,
    })


@simulation_bp.route("/list", methods=["GET"])
def list_simulations():
    """List all simulations."""
    sims = sim_manager.list_all()
    return jsonify({"simulations": sims, "count": len(sims)})


@simulation_bp.route("/<sim_id>/profiles", methods=["GET"])
def get_profiles(sim_id: str):
    """Get agent profiles for a simulation."""
    state = sim_manager.get(sim_id)
    if not state:
        return jsonify({"error": f"Simulation {sim_id} not found"}), 404

    # Try JSON first (richer data)
    json_path = os.path.join(state.output_dir, "profiles.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            profiles = json.load(f)
        return jsonify({"profiles": profiles, "count": len(profiles)})

    # Fallback to CSV
    if not state.profiles_path or not os.path.exists(state.profiles_path):
        return jsonify({"error": "Profiles not generated yet"}), 404

    import csv
    profiles = []
    with open(state.profiles_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            profiles.append(row)

    return jsonify({"profiles": profiles, "count": len(profiles)})


@simulation_bp.route("/<sim_id>/config", methods=["GET"])
def get_config(sim_id: str):
    """Get full simulation config (time, events, rec, reasoning)."""
    state = sim_manager.get(sim_id)
    if not state:
        return jsonify({"error": f"Simulation {sim_id} not found"}), 404

    if not state.config_path or not os.path.exists(state.config_path):
        return jsonify({"error": "Config not generated yet"}), 404

    with open(state.config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    return jsonify(config)


@simulation_bp.route("/<sim_id>/scenarios", methods=["GET"])
def get_scenarios(sim_id: str):
    """Get crisis scenarios."""
    state = sim_manager.get(sim_id)
    if not state:
        return jsonify({"error": f"Simulation {sim_id} not found"}), 404

    if not state.crisis_path or not os.path.exists(state.crisis_path):
        return jsonify({"error": "Crisis scenarios not generated yet"}), 404

    with open(state.crisis_path, "r", encoding="utf-8") as f:
        scenarios = json.load(f)

    return jsonify({"scenarios": scenarios, "count": len(scenarios)})


# ── Phase 4: Simulation Execution ──

@simulation_bp.route("/start", methods=["POST"])
def start_simulation():
    """Start OASIS simulation.

    Request JSON:
        sim_id: str (required)
        scenario_index: int (default 0)
        crisis_trigger_round: int (optional override for crisis trigger round)
    """
    data = request.get_json() or {}
    sim_id = data.get("sim_id", "")
    scenario_index = data.get("scenario_index", 0)
    crisis_trigger_round = data.get("crisis_trigger_round")

    if not sim_id:
        return jsonify({"error": "sim_id is required"}), 400

    # Override crisis trigger round if specified
    if crisis_trigger_round is not None:
        _override_crisis_round(sim_id, crisis_trigger_round)

    from ..services.sim_runner import SimRunner
    runner = SimRunner()
    result = runner.start(sim_id, scenario_index)

    if "error" in result:
        return jsonify(result), 400

    return jsonify(result), 200


def _override_crisis_round(sim_id: str, new_round: int):
    """Override the crisis trigger round in crisis_scenarios.json."""
    state = sim_manager.get(sim_id)
    if not state or not state.crisis_path:
        return

    try:
        with open(state.crisis_path, "r", encoding="utf-8") as f:
            scenarios = json.load(f)

        for sc in scenarios:
            for ev in sc.get("events", []):
                if ev.get("trigger_round"):
                    ev["trigger_round"] = new_round

        with open(state.crisis_path, "w", encoding="utf-8") as f:
            json.dump(scenarios, f, ensure_ascii=False, indent=2)

        logger.info(f"Overrode crisis trigger round to {new_round} for {sim_id}")
    except Exception as e:
        logger.warning(f"Failed to override crisis round: {e}")


@simulation_bp.route("/<sim_id>/progress", methods=["GET"])
def get_progress(sim_id: str):
    """Get simulation progress."""
    from ..services.sim_runner import SimRunner
    runner = SimRunner()
    result = runner.get_progress(sim_id)

    if "error" in result:
        return jsonify(result), 404

    return jsonify(result)


@simulation_bp.route("/<sim_id>/actions", methods=["GET"])
def get_actions(sim_id: str):
    """Get simulation actions from actions.jsonl."""
    limit = request.args.get("limit", 200, type=int)

    from ..services.sim_runner import SimRunner
    runner = SimRunner()
    actions = runner.get_actions(sim_id, limit=limit)

    return jsonify({"actions": actions, "count": len(actions)})


@simulation_bp.route("/<sim_id>/stream", methods=["GET"])
def stream_simulation(sim_id: str):
    """SSE streaming endpoint for real-time simulation updates.

    Returns text/event-stream with events:
        round_start: {round, total_rounds, progress_pct}
        round_actions: {round, actions, action_count}
        crisis: {round, message}
        done: {status}
    """
    from ..services.sim_runner import SimRunner

    state = sim_manager.get(sim_id)
    if not state:
        return jsonify({"error": f"Simulation {sim_id} not found"}), 404

    def generate():
        q = SimRunner.subscribe(sim_id)
        try:
            while True:
                try:
                    event = q.get(timeout=30)  # 30s heartbeat timeout
                except Exception:
                    # Send heartbeat to keep connection alive
                    yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"
                    continue

                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

                # Stop streaming after done event
                if event.get("event") == "done":
                    break
        except GeneratorExit:
            pass
        finally:
            SimRunner.unsubscribe(sim_id, q)

    from flask import Response
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


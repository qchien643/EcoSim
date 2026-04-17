"""
Simulation Manager — State machine + orchestration.

Manages simulation lifecycle: CREATED → PREPARING → READY → RUNNING → COMPLETED
Persists state to disk; reconstructs from filesystem on restart.
"""

import json
import logging
import os
from typing import Dict, List, Optional

from ..config import Config
from ..models.simulation import SimConfig, SimState, SimStatus

logger = logging.getLogger("ecosim.sim_manager")

# In-memory state store (populated on-demand from disk)
_simulations: Dict[str, SimState] = {}


class SimManager:
    """Manage simulation lifecycle."""

    def create(self, campaign_id: str, num_agents: int = 10) -> SimState:
        """Create a new simulation."""
        config = SimConfig(campaign_id=campaign_id, num_agents=num_agents)
        sim_dir = os.path.join(Config.SIM_DIR, config.sim_id)
        os.makedirs(sim_dir, exist_ok=True)

        state = SimState(
            sim_id=config.sim_id,
            campaign_id=campaign_id,
            num_agents=num_agents,
            output_dir=sim_dir,
            total_rounds=config.time_config.total_rounds,
        )
        _simulations[config.sim_id] = state

        # Save config
        config_path = os.path.join(sim_dir, "simulation_config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)
        state.config_path = config_path

        logger.info(f"Simulation created: {config.sim_id}")
        return state

    def update_status(self, sim_id: str, status: SimStatus, error: str = ""):
        """Update simulation status."""
        if sim_id in _simulations:
            _simulations[sim_id].status = status
            if error:
                _simulations[sim_id].error = error
            logger.info(f"Sim {sim_id}: {status.value}")

    def get(self, sim_id: str) -> Optional[SimState]:
        """Get simulation state (checks memory, then disk)."""
        if sim_id in _simulations:
            return _simulations[sim_id]

        # Try reconstruct from disk
        state = self._load_from_disk(sim_id)
        if state:
            _simulations[sim_id] = state
        return state

    def list_all(self) -> List[Dict]:
        """List all simulations (scans data/simulations/ directory)."""
        self._scan_disk()
        return [
            {
                "sim_id": s.sim_id,
                "campaign_id": s.campaign_id,
                "status": s.status.value,
                "num_agents": s.num_agents,
                "current_round": s.current_round,
                "total_rounds": s.total_rounds,
                "created_at": s.created_at.isoformat(),
            }
            for s in _simulations.values()
        ]

    # ── Disk Persistence ──

    def _scan_disk(self):
        """Scan data/simulations/ for sim_* directories and load missing."""
        Config.ensure_dirs()
        if not os.path.isdir(Config.SIM_DIR):
            return

        for entry in os.listdir(Config.SIM_DIR):
            sim_dir = os.path.join(Config.SIM_DIR, entry)
            if os.path.isdir(sim_dir) and entry.startswith("sim_"):
                if entry not in _simulations:
                    state = self._load_from_disk(entry)
                    if state:
                        _simulations[entry] = state

    def _load_from_disk(self, sim_id: str) -> Optional[SimState]:
        """Reconstruct SimState from filesystem artifacts."""
        sim_dir = os.path.join(Config.SIM_DIR, sim_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")

        if not os.path.exists(config_path):
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            # Determine status from existing files
            status = self._infer_status(sim_dir)

            # Count agents from profiles.csv
            num_agents = config_data.get("num_agents", 0)
            profiles_path = os.path.join(sim_dir, "profiles.csv")
            if os.path.exists(profiles_path):
                import csv
                with open(profiles_path, "r", encoding="utf-8") as f:
                    num_agents = max(num_agents, sum(1 for _ in csv.reader(f)) - 1)

            # Count rounds from actions
            current_round = 0
            total_rounds = config_data.get("time_config", {}).get("total_rounds", 24)
            actions_path = os.path.join(sim_dir, "actions.jsonl")
            if os.path.exists(actions_path):
                current_round = total_rounds  # completed

            state = SimState(
                sim_id=sim_id,
                status=status,
                campaign_id=config_data.get("campaign_id", ""),
                num_agents=num_agents,
                profiles_path=profiles_path if os.path.exists(profiles_path) else "",
                config_path=config_path,
                crisis_path=os.path.join(sim_dir, "crisis_scenarios.json")
                    if os.path.exists(os.path.join(sim_dir, "crisis_scenarios.json")) else "",
                output_dir=sim_dir,
                current_round=current_round,
                total_rounds=total_rounds,
            )

            # Try to parse created_at from config
            if "created_at" in config_data:
                try:
                    from datetime import datetime
                    state.created_at = datetime.fromisoformat(str(config_data["created_at"]))
                except (ValueError, TypeError):
                    pass

            return state

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load sim {sim_id} from disk: {e}")
            return None

    @staticmethod
    def _infer_status(sim_dir: str) -> SimStatus:
        """Infer simulation status from directory contents."""
        has_actions = os.path.exists(os.path.join(sim_dir, "actions.jsonl"))
        has_profiles = os.path.exists(os.path.join(sim_dir, "profiles.csv"))
        has_crisis = os.path.exists(os.path.join(sim_dir, "crisis_scenarios.json"))
        has_report = os.path.exists(os.path.join(sim_dir, "report.md"))
        has_log = os.path.exists(os.path.join(sim_dir, "simulation.log"))

        if has_actions:
            return SimStatus.COMPLETED
        if has_log:
            return SimStatus.RUNNING  # or crashed
        if has_profiles and has_crisis:
            return SimStatus.READY
        if has_profiles or has_crisis:
            return SimStatus.PREPARING
        return SimStatus.CREATED

"""
Simulation Manager — State machine + orchestration.

Manages simulation lifecycle: CREATED → PREPARING → READY → RUNNING → COMPLETED.

State resolution (Option A, post-Phase 5):
  1. In-memory cache (_simulations dict)
  2. Meta DB (`data/meta.db` → simulations table) — AUTHORITATIVE for sim_dir,
     status, paths. Phase 5 moved sims out of `Config.SIM_DIR` and into
     `data/campaigns/<cid>/sims/<sid>/`; meta.db indexes the new layout.
  3. Filesystem fallback at legacy `Config.SIM_DIR/<sid>/` for sims NOT in
     meta.db (e.g. very old runs predating the meta index).
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from ecosim_common.atomic_io import atomic_write_json
from ecosim_common.metadata_index import get_simulation, list_simulations

from ..config import Config
from ..models.simulation import SimConfig, SimState, SimStatus

logger = logging.getLogger("ecosim.sim_manager")

# In-memory state store (populated on-demand from meta.db / disk)
_simulations: Dict[str, SimState] = {}


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _parse_status(value: Any) -> SimStatus:
    """Coerce meta.db string → SimStatus enum, default CREATED."""
    if not value:
        return SimStatus.CREATED
    try:
        return SimStatus(str(value).lower())
    except ValueError:
        return SimStatus.CREATED


class SimManager:
    """Manage simulation lifecycle."""

    def create(self, campaign_id: str, num_agents: int = 10) -> SimState:
        """Create a new simulation.

        Note: production path uses `apps/simulation/api/simulation.py:_create_sim`
        which writes meta.db + the per-campaign sim_dir. This Core-side create()
        is kept for legacy tests; it still uses `Config.SIM_DIR` and does NOT
        register in meta.db.
        """
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

        # Save config (atomic write)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        atomic_write_json(config_path, config.model_dump(mode="json"))
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
        """Get simulation state.

        Resolution order:
          1. In-memory cache.
          2. Meta DB row (authoritative for Phase 5 sims under
             data/campaigns/<cid>/sims/<sid>/).
          3. Legacy filesystem scan at Config.SIM_DIR/<sid>/.
        """
        if sim_id in _simulations:
            return _simulations[sim_id]

        # Meta DB lookup (primary path post-Phase 5)
        row = get_simulation(sim_id)
        if row:
            state = self._load_from_meta(row)
            if state:
                _simulations[sim_id] = state
                return state

        # Legacy fallback — sims not registered in meta.db
        state = self._load_from_disk_legacy(sim_id)
        if state:
            _simulations[sim_id] = state
        return state

    def list_all(self) -> List[Dict]:
        """List all simulations (meta.db first, then legacy filesystem scan)."""
        # Hydrate cache from meta.db
        for row in list_simulations(limit=500):
            sid = row.get("sid")
            if sid and sid not in _simulations:
                state = self._load_from_meta(row)
                if state:
                    _simulations[sid] = state

        # Pick up any legacy on-disk sims not in meta.db
        self._scan_disk_legacy()

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

    # ── Meta DB → SimState ──

    def _load_from_meta(self, row: Dict[str, Any]) -> Optional[SimState]:
        """Build SimState from a meta.db simulations row.

        Trusts meta.db for canonical fields (sim_dir, status, paths). If
        the on-disk config exists we still overlay it for richer detail
        (e.g. crisis_path), but never fall back to legacy guesses.
        """
        try:
            sid = row["sid"]
            sim_dir = row.get("sim_dir") or os.path.join(Config.SIM_DIR, sid)
            config_path = row.get("config_path") or os.path.join(sim_dir, "simulation_config.json")
            profiles_path = row.get("profiles_path") or ""
            crisis_path = os.path.join(sim_dir, "crisis_scenarios.json")

            state = SimState(
                sim_id=sid,
                campaign_id=row.get("cid", "") or "",
                status=_parse_status(row.get("status")),
                num_agents=int(row.get("num_agents") or 0),
                current_round=int(row.get("current_round") or 0),
                total_rounds=int(row.get("num_rounds") or 24),
                output_dir=sim_dir,
                config_path=config_path if os.path.exists(config_path) else "",
                profiles_path=profiles_path if profiles_path and os.path.exists(profiles_path) else "",
                crisis_path=crisis_path if os.path.exists(crisis_path) else "",
            )

            created = _parse_dt(row.get("created_at"))
            if created:
                state.created_at = created

            return state
        except (KeyError, ValueError) as e:
            logger.warning("Failed to hydrate sim from meta row: %s", e)
            return None

    # ── Legacy filesystem path (pre Phase 5) ──

    def _scan_disk_legacy(self):
        """Scan legacy `Config.SIM_DIR` for sim_* dirs not in meta.db.

        Phase 5 moved sims into per-campaign subdirs, so this scan typically
        finds nothing. Kept as a safety net for stale local data.
        """
        Config.ensure_dirs()
        if not os.path.isdir(Config.SIM_DIR):
            return

        for entry in os.listdir(Config.SIM_DIR):
            if not entry.startswith("sim_"):
                continue
            sim_dir = os.path.join(Config.SIM_DIR, entry)
            if not os.path.isdir(sim_dir) or entry in _simulations:
                continue
            state = self._load_from_disk_legacy(entry)
            if state:
                _simulations[entry] = state

    def _load_from_disk_legacy(self, sim_id: str) -> Optional[SimState]:
        """Reconstruct SimState from legacy `Config.SIM_DIR/<sid>/` layout."""
        sim_dir = os.path.join(Config.SIM_DIR, sim_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")

        if not os.path.exists(config_path):
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            status = self._infer_status(sim_dir)

            num_agents = config_data.get("num_agents", 0)
            profiles_path = os.path.join(sim_dir, "profiles.csv")
            if os.path.exists(profiles_path):
                import csv
                with open(profiles_path, "r", encoding="utf-8") as f:
                    num_agents = max(num_agents, sum(1 for _ in csv.reader(f)) - 1)

            current_round = 0
            total_rounds = config_data.get("time_config", {}).get("total_rounds", 24)
            actions_path = os.path.join(sim_dir, "actions.jsonl")
            if os.path.exists(actions_path):
                current_round = total_rounds  # completed

            crisis_path = os.path.join(sim_dir, "crisis_scenarios.json")
            state = SimState(
                sim_id=sim_id,
                status=status,
                campaign_id=config_data.get("campaign_id", ""),
                num_agents=num_agents,
                profiles_path=profiles_path if os.path.exists(profiles_path) else "",
                config_path=config_path,
                crisis_path=crisis_path if os.path.exists(crisis_path) else "",
                output_dir=sim_dir,
                current_round=current_round,
                total_rounds=total_rounds,
            )

            created = _parse_dt(config_data.get("created_at"))
            if created:
                state.created_at = created

            return state

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load legacy sim %s: %s", sim_id, e)
            return None

    @staticmethod
    def _infer_status(sim_dir: str) -> SimStatus:
        """Infer simulation status from directory contents (legacy fallback)."""
        has_actions = os.path.exists(os.path.join(sim_dir, "actions.jsonl"))
        has_profiles = os.path.exists(os.path.join(sim_dir, "profiles.csv"))
        has_crisis = os.path.exists(os.path.join(sim_dir, "crisis_scenarios.json"))
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

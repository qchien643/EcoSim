"""
Sim manifest — track quan hệ campaign ↔ sims trong filesystem.

Mỗi campaign có 1 file `data/uploads/<campaign_id>_sims.json` chứa list các
sim đã prepare từ master KG của campaign đó. Manifest cho phép cascade DELETE
campaign nhanh (O(1) lookup vs scan toàn bộ data/simulations/) và filter
`/api/sim/list?campaign_id=X`.

Filesystem là source of truth — không có DB. Recovery: nếu manifest mất,
có thể rebuild bằng cách scan `data/simulations/*/simulation_config.json`
và group theo `campaign_id` field.

Schema (v1):
{
  "campaign_id": "07d9fe34",
  "sims": [
    {
      "sim_id": "sim_a3f1b9c2",
      "graph_name": "sim_a3f1b9c2",       # FalkorDB graph name (= sim_id literal)
      "created_at": "2026-04-25T10:30:00",
      "num_agents": 3,
      "num_rounds": 5
    },
    ...
  ]
}
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .atomic_io import atomic_write_json
from .config import EcoSimConfig


def manifest_path(campaign_id: str) -> Path:
    """Đường dẫn manifest file: <UPLOAD_DIR>/<campaign_id>/sims.json.

    Per-campaign storage layout: mỗi campaign 1 thư mục riêng chứa source/,
    extracted/, kg/, sims.json. Layout cũ flat `<id>_sims.json` đã deprecated.
    """
    if not campaign_id:
        raise ValueError("campaign_id required")
    return EcoSimConfig.campaign_dir(campaign_id) / "sims.json"


def _load(campaign_id: str) -> Dict:
    """Đọc manifest. Trả schema mặc định nếu file chưa có."""
    p = manifest_path(campaign_id)
    if not p.exists():
        return {"campaign_id": campaign_id, "sims": []}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Defensive: ensure schema
        data.setdefault("campaign_id", campaign_id)
        data.setdefault("sims", [])
        return data
    except (json.JSONDecodeError, OSError):
        # Corrupt manifest → start fresh, log via caller
        return {"campaign_id": campaign_id, "sims": []}


def add_sim_to_manifest(
    campaign_id: str,
    sim_id: str,
    graph_name: str,
    *,
    num_agents: int = 0,
    num_rounds: int = 0,
) -> None:
    """Append sim entry vào manifest. Idempotent (skip nếu sim_id đã có)."""
    data = _load(campaign_id)
    if any(s.get("sim_id") == sim_id for s in data["sims"]):
        return
    data["sims"].append({
        "sim_id": sim_id,
        "graph_name": graph_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "num_agents": num_agents,
        "num_rounds": num_rounds,
    })
    atomic_write_json(manifest_path(campaign_id), data)


def remove_sim_from_manifest(campaign_id: str, sim_id: str) -> bool:
    """Remove sim entry. Returns True nếu đã remove, False nếu không tìm thấy."""
    data = _load(campaign_id)
    before = len(data["sims"])
    data["sims"] = [s for s in data["sims"] if s.get("sim_id") != sim_id]
    if len(data["sims"]) == before:
        return False
    atomic_write_json(manifest_path(campaign_id), data)
    return True


def list_sims_for_campaign(campaign_id: str) -> List[Dict]:
    """Return list sim entries của campaign (rỗng nếu chưa có manifest)."""
    return _load(campaign_id)["sims"]


def list_all_campaigns() -> List[str]:
    """Scan upload dir để liệt kê tất cả campaign_id có manifest.

    Glob `<UPLOAD_DIR>/*/sims.json` (per-campaign layout).

    Lưu ý: campaigns mới upload nhưng chưa prepare sim nào sẽ KHÔNG có
    manifest → không xuất hiện trong list. Để liệt kê all campaigns,
    nên scan `<UPLOAD_DIR>/*/extracted/spec.json` thay vì manifest.
    """
    upload_dir = EcoSimConfig.upload_dir()
    if not upload_dir.exists():
        return []
    return sorted([
        p.parent.name
        for p in upload_dir.glob("*/sims.json")
    ])


def delete_manifest(campaign_id: str) -> bool:
    """Xóa manifest file (dùng trong cascade DELETE campaign)."""
    p = manifest_path(campaign_id)
    if p.exists():
        p.unlink()
        return True
    return False


def find_campaign_for_sim(sim_id: str) -> Optional[str]:
    """Reverse lookup: sim_id → campaign_id. Scan tất cả manifests.

    O(N) campaigns. Dùng cho cascade DELETE sim khi không biết campaign_id
    (vd subprocess crash chỉ còn sim_dir, mất state.campaign_id).

    Fallback chính xác hơn: đọc `simulation_config.json` của sim_dir.
    """
    for cid in list_all_campaigns():
        for s in list_sims_for_campaign(cid):
            if s.get("sim_id") == sim_id:
                return cid
    return None

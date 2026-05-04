"""
Build progress tracker — write granular stage updates to JSON file.

KG build pipeline (campaign_knowledge.run_from_text + write_kg_direct) gọi
`update(group_id, stage, percent, message)` ở các checkpoints chính. Frontend
poll endpoint `/api/graph/build-progress?campaign_id=X` mỗi 1.5s để hiển thị
stage message thay vì chỉ "Building..." chung chung.

File path: `<UPLOAD_DIR>/<campaign_id>/kg/build_progress.json`. Atomic write
qua `ecosim_common.atomic_io.atomic_write_json` tránh race khi reader đang
đọc giữa lúc writer ghi.

Schema:
{
    "stage": "embedding_entities",
    "percent": 60,
    "message": "Embedding 31 entities batch...",
    "status": "running" | "done" | "failed",
    "started_at": "2026-04-25T20:00:00",
    "updated_at": "2026-04-25T20:00:12",
    "error": null,    # populated if status=failed
}
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from ecosim_common.atomic_io import atomic_write_json
from ecosim_common.config import EcoSimConfig

logger = logging.getLogger("sim-svc.build_progress")


def _path(group_id: str):
    """Đường dẫn build_progress.json cho campaign — DB-backed resolver."""
    try:
        from ecosim_common.path_resolver import resolve_campaign_paths
        kg_dir = resolve_campaign_paths(group_id).get("kg_dir")
        if kg_dir:
            from pathlib import Path as _Path
            return _Path(kg_dir) / "build_progress.json"
    except Exception:
        pass
    return EcoSimConfig.campaign_kg_dir(group_id) / "build_progress.json"


def start(group_id: str, message: str = "Initializing...") -> None:
    """Đánh dấu start build. Reset progress về 0."""
    if not group_id:
        return
    try:
        path = _path(group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        atomic_write_json(path, {
            "stage": "init",
            "percent": 0,
            "message": message,
            "status": "running",
            "started_at": now,
            "updated_at": now,
            "error": None,
        })
    except Exception as e:
        logger.debug("build_progress.start failed for %s: %s", group_id, e)


def update(
    group_id: str,
    stage: str,
    percent: int,
    message: str = "",
) -> None:
    """Cập nhật stage + percent + message. KHÔNG raise nếu fail (progress
    là metadata, không critical — pipeline phải chạy được kể cả khi không
    write được progress file)."""
    if not group_id:
        return
    try:
        path = _path(group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Read existing để giữ started_at (atomic_write_json overwrites)
        started_at = None
        if path.exists():
            try:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    started_at = json.load(f).get("started_at")
            except Exception:
                pass
        now = datetime.now().isoformat(timespec="seconds")
        atomic_write_json(path, {
            "stage": stage,
            "percent": max(0, min(100, percent)),
            "message": message or stage,
            "status": "running",
            "started_at": started_at or now,
            "updated_at": now,
            "error": None,
        })
    except Exception as e:
        logger.debug("build_progress.update failed for %s: %s", group_id, e)


def done(group_id: str, message: str = "Build complete") -> None:
    """Đánh dấu build xong. Frontend đọc status='done' để stop polling."""
    if not group_id:
        return
    try:
        path = _path(group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        started_at = None
        if path.exists():
            try:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    started_at = json.load(f).get("started_at")
            except Exception:
                pass
        now = datetime.now().isoformat(timespec="seconds")
        atomic_write_json(path, {
            "stage": "done",
            "percent": 100,
            "message": message,
            "status": "done",
            "started_at": started_at or now,
            "updated_at": now,
            "error": None,
        })
    except Exception as e:
        logger.debug("build_progress.done failed for %s: %s", group_id, e)


def failed(group_id: str, error: str) -> None:
    """Đánh dấu build failed với error message."""
    if not group_id:
        return
    try:
        path = _path(group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        started_at = None
        if path.exists():
            try:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    started_at = json.load(f).get("started_at")
            except Exception:
                pass
        atomic_write_json(path, {
            "stage": "failed",
            "percent": 0,
            "message": "Build failed",
            "status": "failed",
            "started_at": started_at or now,
            "updated_at": now,
            "error": str(error)[:500],
        })
    except Exception as e:
        logger.debug("build_progress.failed write failed for %s: %s", group_id, e)


def read(group_id: str) -> Optional[dict]:
    """Đọc current progress. Trả None nếu chưa có file."""
    if not group_id:
        return None
    try:
        import json
        path = _path(group_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

"""
Atomic file I/O — write-to-temp + rename pattern.

Đảm bảo reader không bao giờ thấy file dở (partial write) khi writer đang ghi.
Pattern: write vào `{path}.tmp` rồi `os.replace()` (atomic trên POSIX,
best-effort trên Windows).

Dùng cho mọi JSON/JSONL state files ở `data/simulations/{sim_id}/` và
`data/uploads/{id}_spec.json` để tránh race condition giữa Core + Simulation.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger("ecosim_common.atomic_io")

PathLike = Union[str, Path]


def atomic_write_text(path: PathLike, content: str, *, encoding: str = "utf-8") -> None:
    """Ghi text atomically: tmp → fsync → rename.

    Raises OSError nếu target không writable. Windows có thể fail nếu file
    đích đang mở ở chỗ khác — fallback plain write + warn.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # mkstemp cùng directory để đảm bảo rename atomic (cùng filesystem)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=target.name + ".",
        suffix=".tmp",
        text=False,
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(tmp_path, target)
        except OSError as e:
            # Windows: target đang mở → fallback
            logger.warning("atomic rename failed for %s (%s), falling back to plain write", target, e)
            Path(target).write_text(content, encoding=encoding)
            os.unlink(tmp_path)
    except Exception:
        # Dọn tmp nếu ghi thất bại giữa chừng
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(
    path: PathLike,
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
) -> None:
    """Serialize `data` → JSON → atomic write."""
    content = json.dumps(
        data, indent=indent, ensure_ascii=ensure_ascii, sort_keys=sort_keys,
    )
    atomic_write_text(path, content)


def atomic_append_jsonl(path: PathLike, record: Dict[str, Any]) -> None:
    """Append 1 record vào file JSONL — dùng O_APPEND để atomic trên POSIX.

    Không dùng write-to-tmp pattern vì append cần per-line atomicity
    (multiple writers có thể append cùng lúc). OS POSIX đảm bảo O_APPEND
    atomic cho write < PIPE_BUF (thường 4096 bytes/line).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(target, "a", encoding="utf-8") as f:
        f.write(line)


def safe_read_json(
    path: PathLike,
    default: Optional[Any] = None,
    *,
    encoding: str = "utf-8",
) -> Any:
    """Đọc JSON, trả default nếu file không tồn tại hoặc JSON rách.

    Phù hợp cho state files mà reader có thể race với writer
    (vd: progress.json trong lúc subprocess đang ghi).
    """
    try:
        target = Path(path)
        if not target.exists():
            return default
        text = target.read_text(encoding=encoding)
        if not text.strip():
            return default
        return json.loads(text)
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("safe_read_json(%s) returned default: %s", path, e)
        return default

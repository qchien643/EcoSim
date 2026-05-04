"""
Auto-evict cron — Phase 3.3 storage hygiene.

Background daemon thread scan `simulations` table mỗi `interval_seconds`,
evict sim graphs khỏi FalkorDB nếu:
  • status = 'completed'
  • last_accessed_at > max_age_days
  • Có disk delta (`<sim_dir>/kg/snapshot_delta.json`) — an toàn restore lazy

Disk state KEEP nguyên — chỉ drop FalkorDB graph để giải phóng memory.
User access lại → cascade_restore_sim auto-trigger qua existing `/restore-kg`.

Tunables qua env:
  SIM_EVICT_INTERVAL_S=3600    (default 1h)
  SIM_EVICT_MAX_AGE_DAYS=7     (default 7 ngày)
  SIM_EVICT_ENABLED=true       (default on)
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("sim-svc.evict_cron")

_started = False
_lock = threading.Lock()


def _scan_and_evict(max_age_days: int) -> int:
    """One pass scan. Returns count evicted."""
    from ecosim_common.metadata_index import list_simulations

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat(timespec="seconds")
    evicted = 0
    sims = list_simulations(status="completed")
    for s in sims:
        last_accessed = s.get("last_accessed_at") or "0000"
        if last_accessed >= cutoff:
            continue
        sid = s["sid"]
        # Phase 10: FalkorDB là source of truth cho graph data — không còn
        # snapshot_delta.json để check. Evict idle sim graphs trực tiếp;
        # nếu user cần lại sẽ phải re-prepare (clone master + re-seed agents).
        try:
            from sim_graph_clone import drop_sim_graph
            if drop_sim_graph(sid):
                evicted += 1
                logger.info(
                    "Auto-evicted sim %s (idle since %s, threshold %dd)",
                    sid, last_accessed, max_age_days,
                )
        except Exception as e:
            logger.warning("Evict %s failed: %s", sid, e)
    return evicted


def start_evict_cron(
    interval_seconds: Optional[int] = None,
    max_age_days: Optional[int] = None,
) -> Optional[threading.Thread]:
    """Idempotent — gọi 1 lần ở sim_service boot. Returns thread handle hoặc None.

    Disabled khi env SIM_EVICT_ENABLED=false. Tham số None → đọc env.
    """
    global _started
    with _lock:
        if _started:
            logger.debug("Evict cron already started")
            return None
        if os.getenv("SIM_EVICT_ENABLED", "true").lower() != "true":
            logger.info("Evict cron disabled via SIM_EVICT_ENABLED=false")
            return None

        _interval = interval_seconds if interval_seconds is not None else int(
            os.getenv("SIM_EVICT_INTERVAL_S", "3600")
        )
        _max_age = max_age_days if max_age_days is not None else int(
            os.getenv("SIM_EVICT_MAX_AGE_DAYS", "7")
        )

        def _loop():
            logger.info("Evict cron started: interval=%ds, max_age=%dd", _interval, _max_age)
            while True:
                try:
                    n = _scan_and_evict(_max_age)
                    if n:
                        logger.info("Evict cycle: %d sim(s) evicted", n)
                except Exception as e:
                    logger.warning("Evict cycle exception: %s", e)
                # Sleep AFTER scan để kick first scan ngay sau boot
                import time as _time
                _time.sleep(_interval)

        t = threading.Thread(target=_loop, daemon=True, name="sim-evict-cron")
        t.start()
        _started = True
        return t

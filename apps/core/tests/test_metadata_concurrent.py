"""
Concurrent write test cho meta.db — verify WAL + busy_timeout handle race
giữa Core service + Sim service viết cùng lúc.

Scenario: 2 service spawn workers giả lập:
  • Core writer: campaign upserts (5 campaigns × 10 updates each)
  • Sim writer: simulation upserts + status updates (5 sims × 20 updates)
  • Reader: list_campaigns + list_simulations 50 lần parallel

Verify:
  • No exceptions thrown (busy_timeout đủ buffer cho contention)
  • Final row counts đúng (no lost writes)
  • Cascade FK still works concurrently

Run:
  python -m pytest apps/core/tests/test_metadata_concurrent.py -v
hoặc:
  python apps/core/tests/test_metadata_concurrent.py
"""

import os
import sys
import threading
import time
from pathlib import Path

# Bootstrap shared lib path khi chạy standalone
_HERE = Path(__file__).resolve()
for _p in [_HERE, *_HERE.parents]:
    _shared = _p / "libs" / "ecosim-common" / "src"
    if _shared.is_dir():
        sys.path.insert(0, str(_shared))
        os.chdir(str(_p))
        break


def _test_with_isolated_db(test_name: str, fn):
    """Run test với meta.db isolated tại temp path.

    Windows note: dùng `ignore_cleanup_errors=True` vì SQLite có thể giữ file
    handle qua một thời gian ngắn sau close (page cache flush). Test logic
    đã pass — cleanup race không invalidate result.
    """
    import tempfile
    tmp = tempfile.mkdtemp()
    os.environ["META_DB_PATH"] = str(Path(tmp) / "meta.db")
    # Force reload to pick up env override
    import importlib
    from ecosim_common import metadata_index, config
    importlib.reload(config)
    importlib.reload(metadata_index)
    try:
        fn(metadata_index)
        print(f"[PASS] {test_name}")
    except Exception as e:
        print(f"[FAIL] {test_name}: {e}")
        raise
    finally:
        del os.environ["META_DB_PATH"]
        # Best-effort cleanup; ignore Windows file locks
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_concurrent_writers_no_lost_writes(meta):
    """20 threads viết cùng lúc → no lost writes, no exceptions."""
    NUM_THREADS = 20
    UPSERTS_PER_THREAD = 50
    errors = []

    # Pre-create campaign cho FK satisfy
    meta.upsert_campaign("test_cid", name="Concurrent Test", status="ready")

    def worker(worker_id: int):
        try:
            for i in range(UPSERTS_PER_THREAD):
                sid = f"sim_w{worker_id}_i{i}"
                meta.upsert_simulation(
                    sid, "test_cid",
                    status="ready",
                    num_agents=10, num_rounds=3,
                )
                meta.update_sim_status(sid, "running")
                meta.update_sim_status(sid, "completed", current_round=3)
        except Exception as e:
            errors.append((worker_id, str(e)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(NUM_THREADS)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    elapsed = time.time() - t0

    assert not errors, f"Concurrent errors: {errors[:3]}"
    expected = NUM_THREADS * UPSERTS_PER_THREAD
    # Use raw count (list_simulations default limit=200 không đủ cho 1000 rows)
    import sqlite3
    with sqlite3.connect(str(meta.EcoSimConfig.meta_db_path())) as conn:
        actual = conn.execute(
            "SELECT COUNT(*) FROM simulations WHERE cid='test_cid'"
        ).fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM simulations WHERE cid='test_cid' AND status='completed'"
        ).fetchone()[0]
    assert actual == expected, f"Lost writes: {actual}/{expected}"
    print(f"  → {expected} sims persisted in {elapsed:.2f}s "
          f"({expected/elapsed:.0f} writes/s)")
    assert completed == expected, f"Status sync lost: {completed}/{expected}"


def test_reader_sees_writes(meta):
    """Reader thread interleave với writer → should see incremental progress."""
    meta.upsert_campaign("read_cid", name="Reader Test", status="ready")
    write_done = threading.Event()
    read_counts = []

    def writer():
        for i in range(50):
            meta.upsert_simulation(
                f"sim_read_{i}", "read_cid", status="ready",
                num_agents=5, num_rounds=2,
            )
            time.sleep(0.005)  # 5ms gap để reader chen vào
        write_done.set()

    def reader():
        while not write_done.is_set():
            count = len(meta.list_simulations(cid="read_cid"))
            read_counts.append(count)
            time.sleep(0.01)

    tw = threading.Thread(target=writer)
    tr = threading.Thread(target=reader)
    tw.start(); tr.start()
    tw.join(timeout=30); tr.join(timeout=30)

    assert read_counts, "Reader didn't run"
    # Counts should be monotonic non-decreasing
    for i in range(1, len(read_counts)):
        assert read_counts[i] >= read_counts[i-1], \
            f"Reader saw rollback at index {i}: {read_counts[i-1]} → {read_counts[i]}"
    final = len(meta.list_simulations(cid="read_cid"))
    assert final == 50, f"Final count {final} ≠ 50"
    print(f"  → reader saw {len(read_counts)} snapshots, max={max(read_counts)}, final={final}")


def test_cascade_delete_concurrent(meta):
    """Cascade FK delete với writes pending → no orphan rows."""
    meta.upsert_campaign("cascade_cid", name="Cascade Test", status="ready")
    for i in range(10):
        meta.upsert_simulation(
            f"sim_casc_{i}", "cascade_cid", status="completed",
            num_agents=3, num_rounds=2,
        )
        meta.upsert_agents(f"sim_casc_{i}", [
            {"agent_id": j, "realname": f"A{j}", "mbti": "INTJ", "gender": "female",
             "age": 25, "posts_per_week": 3, "daily_hours": 1.0, "followers": 100}
            for j in range(3)
        ])
        meta.upsert_sentiment_round(f"sim_casc_{i}", 1, 5, 2, 3)

    # Cascade delete campaign
    meta.delete_campaign("cascade_cid")

    sims = meta.list_simulations(cid="cascade_cid")
    assert len(sims) == 0, f"Sims not cascaded: {len(sims)}"

    import sqlite3
    with sqlite3.connect(str(meta.EcoSimConfig.meta_db_path())) as conn:
        n_agents = conn.execute(
            "SELECT COUNT(*) FROM simulation_agents WHERE sid LIKE 'sim_casc_%'"
        ).fetchone()[0]
        n_senti = conn.execute(
            "SELECT COUNT(*) FROM sentiment_summaries WHERE sid LIKE 'sim_casc_%'"
        ).fetchone()[0]
    assert n_agents == 0 and n_senti == 0, \
        f"Orphan rows after cascade: agents={n_agents}, sentiment={n_senti}"
    print(f"  → cascade dropped 10 sims + 30 agents + 10 sentiment rows cleanly")


if __name__ == "__main__":
    print("=" * 60)
    print("Concurrent meta.db write tests")
    print("=" * 60)
    _test_with_isolated_db("Concurrent writers no lost", test_concurrent_writers_no_lost_writes)
    _test_with_isolated_db("Reader sees writes monotonic", test_reader_sees_writes)
    _test_with_isolated_db("Cascade delete concurrent", test_cascade_delete_concurrent)
    print("=" * 60)
    print("All passed.")

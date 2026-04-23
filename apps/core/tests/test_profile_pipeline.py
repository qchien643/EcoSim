"""
End-to-End Test for ProfileGenerator Pipeline.

Tests the complete 3-phase pipeline:
  Phase 1: Parquet sampling (real data)
  Phase 2: LLM completion (fallback mode — no API key required)
  Phase 3: Assembly → AgentProfile objects → CSV/JSON export

Run: python tests/test_profile_pipeline.py
"""

import json
import os
import sys
import time
import tempfile
import io

# Fix Windows console encoding for Vietnamese output
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Fix imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.parquet_reader import ParquetProfileReader
from app.services.profile_generator import ProfileGenerator, BEHAVIOR_RULES, MBTI_TYPES
from app.services.name_pool import NamePool
from app.models.simulation import AgentProfile


# ── Resolve parquet path ──
PARQUET_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "dataGenerator", "profile.parquet")
)


def test_parquet_reader():
    """Test ParquetProfileReader independently."""
    print("\n" + "=" * 60)
    print("TEST 1: ParquetProfileReader")
    print("=" * 60)

    reader = ParquetProfileReader(PARQUET_PATH)

    # 1.1 Row count
    count = reader.get_row_count()
    assert count > 0, f"Expected >0 rows, got {count}"
    print(f"  [PASS] Row count: {count:,}")

    # 1.2 Available domains
    domains = reader.get_available_domains(10)
    assert len(domains) > 0, "Expected at least 1 domain"
    print(f"  [PASS] Top domains: {[d['domain'][:25] for d in domains[:5]]}")

    # 1.3 Random sampling
    t0 = time.time()
    samples = reader.sample_random(10)
    t1 = time.time()
    assert len(samples) == 10, f"Expected 10 samples, got {len(samples)}"
    assert all("persona" in s for s in samples), "Missing 'persona' key"
    assert all(len(s["persona"]) > 30 for s in samples), "Persona too short"
    print(f"  [PASS] Random sampling: 10 profiles in {t1 - t0:.2f}s")

    # 1.4 Domain-filtered sampling
    t0 = time.time()
    filtered = reader.sample_by_domains(["Computer Science", "Economics"], 5)
    t1 = time.time()
    assert len(filtered) > 0, "Domain filter returned 0 results"
    print(f"  [PASS] Domain sampling: {len(filtered)} profiles in {t1 - t0:.2f}s")

    # 1.5 Keyword sampling
    kw_results = reader.sample_by_keywords(["software", "developer"], 3)
    print(f"  [PASS] Keyword sampling: {len(kw_results)} profiles")

    # 1.6 Clean quoted values
    assert reader._clean_quoted('"Computer Science"') == "Computer Science"
    assert reader._clean_quoted('"None"') == "None"
    assert reader._clean_quoted("") == ""
    print(f"  [PASS] Quote cleaning: OK")

    reader.close()
    print("  [PASS] Reader closed successfully")
    return True


def test_name_pool():
    """Test NamePool uniqueness."""
    print("\n" + "=" * 60)
    print("TEST 2: NamePool")
    print("=" * 60)

    pool = NamePool(seed=42)
    names = set()
    for i in range(50):
        name = pool.pick()
        assert name not in names, f"Duplicate name at index {i}"
        names.add(name)

    print(f"  [PASS] Generated 50 unique names")
    # Avoid printing Vietnamese chars directly (Windows console issue)
    print(f"  [PASS] Sample count: {len(list(names)[:3])} names")

    pool.reset()
    assert pool.used_count == 0
    print(f"  [PASS] Pool reset OK")
    return True


def test_behavior_rules():
    """Test behavior assignment logic."""
    print("\n" + "=" * 60)
    print("TEST 3: Behavior Rules")
    print("=" * 60)

    from app.services.profile_generator import ProfileGenerator
    pg = ProfileGenerator.__new__(ProfileGenerator)

    for role in ["consumer", "seller", "media", "investor", "regulator", "influencer"]:
        behavior = pg._assign_behavior(role, "neutral")
        assert "stance" in behavior, f"Missing stance for {role}"
        assert "activity_level" in behavior, f"Missing activity_level for {role}"
        assert "posting_probability" in behavior, f"Missing posting_probability for {role}"
        assert "active_hours" in behavior, f"Missing active_hours for {role}"
        assert 0 <= behavior["activity_level"] <= 1, f"Invalid activity_level for {role}"
        assert behavior["response_delay_min"] >= 1, f"Invalid delay_min for {role}"
        assert behavior["response_delay_max"] > behavior["response_delay_min"], f"delay_max <= delay_min for {role}"

    print(f"  [PASS] All 6 roles have valid behavior configs")

    # Test stance mapping
    for stance in ["supportive", "opposing", "neutral"]:
        b = pg._assign_behavior("consumer", stance)
        print(f"  [PASS] Stance '{stance}' -> numeric {b['stance']:.2f}")

    return True


def test_full_pipeline_fallback():
    """Test full pipeline using fallback (no LLM API key needed)."""
    print("\n" + "=" * 60)
    print("TEST 4: Full Pipeline (Fallback Mode)")
    print("=" * 60)

    # Create profile generator with a dummy LLM client that will fail
    # This forces fallback completion for all profiles
    class FailingLLMClient:
        def chat_json(self, *args, **kwargs):
            raise ConnectionError("No API key — testing fallback mode")
        def chat(self, *args, **kwargs):
            raise ConnectionError("No API key — testing fallback mode")

    pg = ProfileGenerator(
        llm_client=FailingLLMClient(),
        parquet_path=PARQUET_PATH,
    )

    num_agents = 10
    t0 = time.time()
    profiles = pg.generate(
        campaign_id="test_campaign",
        num_agents=num_agents,
        campaign_context="E-commerce flash sale campaign for Vietnamese market. "
                         "Focus on technology products and consumer electronics.",
    )
    t1 = time.time()

    # Validate results
    assert len(profiles) == num_agents, f"Expected {num_agents}, got {len(profiles)}"
    print(f"  [PASS] Generated {len(profiles)} profiles in {t1 - t0:.2f}s")

    # Validate each profile
    names = set()
    for p in profiles:
        assert isinstance(p, AgentProfile), f"Expected AgentProfile, got {type(p)}"
        assert p.name, f"Agent {p.agent_id} has empty name"
        assert p.name not in names, f"Duplicate name: {p.name}"
        names.add(p.name)
        assert p.user_char, f"Agent {p.agent_id} has empty user_char"
        assert p.persona, f"Agent {p.agent_id} has empty persona"
        assert p.handle.startswith("@"), f"Agent {p.agent_id} handle doesn't start with @"
        assert 18 <= p.age <= 65, f"Agent {p.agent_id} invalid age: {p.age}"
        assert p.gender in ("male", "female", "other"), f"Agent {p.agent_id} invalid gender: {p.gender}"
        assert p.mbti in MBTI_TYPES, f"Agent {p.agent_id} invalid MBTI: {p.mbti}"
        assert len(p.active_hours) > 0, f"Agent {p.agent_id} no active hours"
        assert p.response_delay_min >= 1, f"Agent {p.agent_id} invalid delay_min"
        assert p.response_delay_max > p.response_delay_min, f"Agent {p.agent_id} delay_max <= delay_min"

    print(f"  [PASS] All {len(profiles)} profiles validated")
    print(f"  [PASS] Unique names: {len(names)}")

    # Test CSV export
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "profiles.csv")
        pg.save_csv(profiles, csv_path)
        assert os.path.exists(csv_path), "CSV file not created"

        # Read back and validate
        import csv
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == num_agents, f"CSV has {len(rows)} rows, expected {num_agents}"

        # Check OASIS-required columns
        required_cols = ["username", "name", "description", "user_char",
                         "following_agentid_list", "previous_tweets"]
        for col in required_cols:
            assert col in rows[0], f"Missing OASIS column: {col}"

        # Check no newlines in text fields (OASIS requirement)
        for row in rows:
            for field in ["user_char", "persona", "bio", "description"]:
                if row.get(field):
                    assert "\n" not in row[field], f"Newline in {field}"
                    assert "\r" not in row[field], f"Carriage return in {field}"

        print(f"  [PASS] CSV export: {csv_path}")
        print(f"  [PASS] OASIS columns: {required_cols}")
        print(f"  [PASS] No newlines in text fields")

        # Test JSON export
        json_path = os.path.join(tmpdir, "profiles.json")
        pg.save_json(profiles, json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)
        assert len(json_data) == num_agents
        print(f"  [PASS] JSON export: {len(json_data)} profiles")

    pg.close()
    print(f"  [PASS] Pipeline closed cleanly")
    return True


def test_domain_extraction():
    """Test campaign context → domain extraction."""
    print("\n" + "=" * 60)
    print("TEST 5: Domain Extraction")
    print("=" * 60)

    pg = ProfileGenerator.__new__(ProfileGenerator)

    # Test various campaign contexts
    test_cases = [
        (
            "E-commerce flash sale campaign for technology products and online shopping",
            ["technology", "business", "retail"],
        ),
        (
            "Healthcare awareness campaign focusing on wellness",
            ["health"],
        ),
        (
            "Marketing promotion for sustainable food delivery service",
            ["marketing", "food", "logistics"],
        ),
        (
            "An unrelated campaign about cats",
            [],
        ),
    ]

    for ctx, expected_subset in test_cases:
        domains = pg._extract_domains_from_context(ctx)
        for d in expected_subset:
            assert d in domains, f"Expected '{d}' in domains for context: {ctx[:50]}... Got: {domains}"
        print(f"  [PASS] '{ctx[:50]}...' -> {domains}")

    return True


def test_merge_behavior_configs():
    """Test merging behavior configs from SimConfigGenerator."""
    print("\n" + "=" * 60)
    print("TEST 6: Merge Behavior Configs")
    print("=" * 60)

    pg = ProfileGenerator.__new__(ProfileGenerator)

    # Create test profiles
    profiles = [
        AgentProfile(agent_id=0, name="Test1", role="consumer"),
        AgentProfile(agent_id=1, name="Test2", role="seller"),
    ]

    # Behavior configs from SimConfigGenerator
    behavior_configs = [
        {"agent_id": 0, "stance_label": "supportive", "activity_level": 0.9},
        {"agent_id": 1, "stance_label": "opposing", "influence_score": 2.5},
    ]

    merged = pg.merge_behavior_configs(profiles, behavior_configs)
    assert merged[0].stance_label == "supportive"
    assert merged[0].activity_level == 0.9
    assert merged[1].stance_label == "opposing"
    assert merged[1].influence_score == 2.5
    print(f"  [PASS] Merged configs correctly")
    return True


def test_performance():
    """Test sampling performance at scale."""
    print("\n" + "=" * 60)
    print("TEST 7: Performance Benchmarks")
    print("=" * 60)

    reader = ParquetProfileReader(PARQUET_PATH)

    # Benchmark random sampling
    for n in [10, 50, 100]:
        t0 = time.time()
        samples = reader.sample_random(n)
        t1 = time.time()
        elapsed = t1 - t0
        print(f"  [PERF] sample_random({n}): {len(samples)} profiles in {elapsed:.2f}s")
        assert elapsed < 30, f"Too slow: {elapsed:.2f}s for {n} samples"

    # Benchmark domain sampling
    t0 = time.time()
    samples = reader.sample_by_domains(["Computer Science", "Economics"], 20)
    t1 = time.time()
    print(f"  [PERF] sample_by_domains(2 domains, 20): {len(samples)} in {t1 - t0:.2f}s")

    reader.close()
    print(f"  [PASS] All performance tests passed")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("EcoSim ProfileGenerator E2E Test Suite")
    print(f"Parquet: {PARQUET_PATH}")
    print(f"Exists: {os.path.exists(PARQUET_PATH)}")
    print("=" * 60)

    if not os.path.exists(PARQUET_PATH):
        print("[FATAL] profile.parquet not found!")
        sys.exit(1)

    results = {}
    tests = [
        ("ParquetReader", test_parquet_reader),
        ("NamePool", test_name_pool),
        ("BehaviorRules", test_behavior_rules),
        ("DomainExtraction", test_domain_extraction),
        ("MergeBehavior", test_merge_behavior_configs),
        ("FullPipeline", test_full_pipeline_fallback),
        ("Performance", test_performance),
    ]

    total_start = time.time()
    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            test_fn()
            results[name] = "PASS"
            passed += 1
        except Exception as e:
            results[name] = f"FAIL: {e}"
            failed += 1
            import traceback
            traceback.print_exc()

    total_time = time.time() - total_start

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for name, result in results.items():
        status = "PASS" if result == "PASS" else "FAIL"
        icon = "+" if status == "PASS" else "X"
        print(f"  [{icon}] {name}: {result}")

    print(f"\n  Total: {passed} passed, {failed} failed ({total_time:.1f}s)")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)

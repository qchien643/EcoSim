"""
E2E Pipeline Test: Campaign File → 5 OASIS Reddit-Compatible Agents

Simulates the real flow:
1. Read campaign markdown file
2. Extract campaign context
3. Sample personas from parquet (60% domain-relevant, 40% random)
4. Pick names from NamePool → LLM batch-complete with name + campaign
5. Assemble AgentProfile objects (8 fields only)
6. Print detailed output for inspection

Usage: python tests/test_campaign_pipeline.py
"""

import json
import os
import sys
import io
import time

# Fix Windows console encoding for Vietnamese/Unicode output
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.profile_generator import ProfileGenerator
from app.models.simulation import AgentProfile


# ── Config ──
CAMPAIGN_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "shopee_blackfriday_2026.md")
)
PARQUET_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "dataGenerator", "profile.parquet")
)
NUM_AGENTS = 5


def read_campaign_file(path: str) -> str:
    """Read campaign markdown and build context string."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return content[:2000]


def print_agent_detail(idx: int, p: AgentProfile):
    """Print a single agent's full profile — OASIS Reddit format."""
    print(f"\n{'─' * 70}")
    print(f"  AGENT #{p.agent_id} — {p.realname}")
    print(f"{'─' * 70}")
    print(f"  Username:   {p.username}")
    print(f"  Realname:   {p.realname}")
    print(f"  Age:        {p.age}")
    print(f"  Gender:     {p.gender}")
    print(f"  MBTI:       {p.mbti}")
    print(f"  Country:    {p.country}")
    print()
    print(f"  Bio:")
    print(f"    {p.bio}")
    print()
    print(f"  Persona (OASIS system prompt) — first 500 chars:")
    persona_preview = p.persona[:500] if p.persona else "(empty)"
    for line in persona_preview.split(". "):
        print(f"    {line.strip()}")

    # Validation checks
    print()
    name_in_persona = p.realname in p.persona
    country_ok = p.country == "Vietnam"
    print(f"  ✅ Name in persona: {'YES' if name_in_persona else '❌ NO'}")
    print(f"  ✅ Country=Vietnam: {'YES' if country_ok else '❌ NO'}")


def main():
    print("=" * 70)
    print("  EcoSim Pipeline Test: Campaign → 5 OASIS Reddit Agents")
    print("=" * 70)

    # ── Step 1: Read campaign file ──
    print(f"\n[Step 1] Reading campaign file...")
    print(f"  Path: {CAMPAIGN_FILE}")
    assert os.path.exists(CAMPAIGN_FILE), f"Campaign file not found: {CAMPAIGN_FILE}"
    campaign_context = read_campaign_file(CAMPAIGN_FILE)
    print(f"  Context length: {len(campaign_context)} chars")
    print(f"  Preview: {campaign_context[:150]}...")

    # ── Step 2: Initialize ProfileGenerator ──
    print(f"\n[Step 2] Initializing ProfileGenerator...")
    print(f"  Parquet: {PARQUET_PATH}")
    assert os.path.exists(PARQUET_PATH), f"Parquet file not found: {PARQUET_PATH}"

    pg = ProfileGenerator(parquet_path=PARQUET_PATH)
    print(f"  OK — connected to DuckDB")

    # ── Step 3: Generate 5 agents ──
    print(f"\n[Step 3] Generating {NUM_AGENTS} agents...")
    print(f"  Pipeline: SAMPLE(parquet) → NAME(pool) → LLM_COMPLETE(batch) → ASSEMBLE(8 fields)")

    def progress_cb(current, total, msg):
        pct = int(current / max(total, 1) * 100)
        print(f"  [{pct:3d}%] {msg}")

    t0 = time.time()
    profiles = pg.generate(
        campaign_id="shopee_blackfriday_2026",
        num_agents=NUM_AGENTS,
        campaign_context=campaign_context,
        batch_size=5,
        progress_callback=progress_cb,
    )
    t1 = time.time()

    print(f"\n  Generated {len(profiles)} agents in {t1 - t0:.1f}s")

    # ── Step 4: Print detailed results ──
    print(f"\n{'=' * 70}")
    print(f"  AGENT PROFILES — OASIS Reddit Format")
    print(f"{'=' * 70}")

    for i, p in enumerate(profiles):
        print_agent_detail(i, p)

    # ── Step 5: Save OASIS Reddit JSON ──
    output_dir = os.path.join(os.path.dirname(__file__), "..", "test_output")
    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, "test_profiles.json")
    pg.save_json(profiles, json_path)

    print(f"\n{'=' * 70}")
    print(f"  OUTPUT FILES")
    print(f"{'=' * 70}")
    print(f"  JSON (OASIS Reddit): {os.path.abspath(json_path)}")

    # ── Step 6: Verify campaign awareness ──
    print(f"\n{'=' * 70}")
    print(f"  CAMPAIGN AWARENESS CHECK")
    print(f"{'=' * 70}")

    campaign_keywords = ["shopee", "black friday", "sale", "flash", "giảm giá",
                         "voucher", "freeship", "khuyến mãi"]
    for p in profiles:
        persona_lower = (p.persona or "").lower()
        found_keywords = [kw for kw in campaign_keywords if kw in persona_lower]
        status = "✅ YES" if found_keywords else "❌ NO"
        print(f"  Agent #{p.agent_id} ({p.realname}): Campaign aware = {status}")
        if found_keywords:
            print(f"    Keywords found: {found_keywords}")

    # ── Step 7: Validate OASIS compatibility ──
    print(f"\n{'=' * 70}")
    print(f"  OASIS COMPATIBILITY CHECK")
    print(f"{'=' * 70}")

    required_fields = {"realname", "username", "bio", "persona", "age", "gender", "mbti", "country"}
    with open(json_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)

    for agent in saved_data:
        missing = required_fields - set(agent.keys())
        extra = set(agent.keys()) - required_fields
        agent_name = agent.get("realname", "?")
        if missing:
            print(f"  ❌ {agent_name}: MISSING fields: {missing}")
        elif extra:
            print(f"  ⚠️ {agent_name}: Extra fields (ok): {extra}")
        else:
            print(f"  ✅ {agent_name}: Perfect — exactly 8 OASIS fields")

    pg.close()
    print(f"\n  Done! DuckDB connection closed.")


if __name__ == "__main__":
    main()

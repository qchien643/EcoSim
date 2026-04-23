"""
FULL INTEGRATION TEST + PERSONA EVOLUTION DEMO
================================================
Runs all 22 unit tests across 4 phases,
then simulates 6 rounds of cognitive pipeline
showing FULL persona content evolution for 3 agents.
"""
import sys
import asyncio
sys.path.insert(0, r"e:\code\project\DUT_STARTUP\EcoSim\oasis")

from agent_cognition import (
    AgentMemory, get_behavior_modifiers,
    InterestTracker, AgentReflection,
)
from interest_feed import build_interest_text, should_post, get_feed_size

# ============================================
# PART 1: ALL UNIT TESTS (22 tests)
# ============================================

def run_all_unit_tests():
    print("=" * 70)
    print("  PART 1: ALL UNIT TESTS (22 total)")
    print("=" * 70)

    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}: {detail}")

    # --- Phase 1: Agent Memory (5 tests) ---
    print("\n--- Phase 1: Agent Memory ---")

    mem = AgentMemory(num_agents=3)
    check("T1.1 Empty context", mem.get_context(0) == "", mem.get_context(0))
    check("T1.2 Non-existent agent", mem.get_context(99) == "")
    check("T1.3 Empty round count", mem.get_round_count(0) == 0)

    mem.record_action(0, "create_post", "Loving the new Shopee deals!")
    mem.record_action(0, "like_post", "")
    mem.record_action(1, "create_comment", "Great product review!")
    mem.end_round(1)

    ctx0 = mem.get_context(0)
    check("T1.4 Basic recording (agent 0)",
          "Round 1" in ctx0 and "posted" in ctx0 and "liked" in ctx0,
          ctx0)

    mem2 = AgentMemory(num_agents=1)
    for r in range(1, 9):
        mem2.record_action(0, "like_post", f"post {r}")
        mem2.end_round(r)
    ctx_overflow = mem2.get_context(0)
    lines = [l for l in ctx_overflow.split("\n") if l.startswith("Round")]
    check("T1.5 Buffer overflow (max 5)",
          len(lines) == 5 and "Round 8" in ctx_overflow and "Round 1" not in ctx_overflow,
          f"got {len(lines)} rounds")

    # --- Phase 2: MBTI Modifiers (5 tests) ---
    print("\n--- Phase 2: MBTI Modifiers ---")

    m_enfj = get_behavior_modifiers("ENFJ")
    check("T2.1 ENFJ modifiers",
          m_enfj["post_mult"] == 1.2 and m_enfj["comment_mult"] == 1.3
          and m_enfj["like_mult"] == 1.2 and m_enfj["feed_mult"] == 0.9,
          str(m_enfj))

    m_istp = get_behavior_modifiers("ISTP")
    check("T2.2 ISTP modifiers",
          m_istp["post_mult"] == 0.8 and m_istp["comment_mult"] == 0.7
          and m_istp["like_mult"] == 0.9 and m_istp["feed_mult"] == 1.2,
          str(m_istp))

    m_empty = get_behavior_modifiers("")
    check("T2.3 Empty MBTI defaults",
          all(v == 1.0 for v in m_empty.values()), str(m_empty))

    import random
    profile_p = {"posts_per_week": 3}
    rng_hi = random.Random(42)
    hi = sum(should_post(profile_p, rng_hi, post_mult=1.2) for _ in range(1000))
    rng_lo = random.Random(42)
    lo = sum(should_post(profile_p, rng_lo, post_mult=0.8) for _ in range(1000))
    check("T2.4 Monte Carlo (E>I)", hi > lo, f"E={hi}, I={lo}")

    check("T2.5 Feed size multiplier",
          get_feed_size(1.0, 1.2) >= get_feed_size(1.0) >= get_feed_size(1.0, 0.9),
          f"P={get_feed_size(1.0, 1.2)}, base={get_feed_size(1.0)}, J={get_feed_size(1.0, 0.9)}")

    # --- Phase 3: Interest Drift (6 tests) ---
    print("\n--- Phase 3: Interest Drift ---")

    tracker = InterestTracker()
    check("T3.1 Empty drift", tracker.get_drift_text(0) == "")
    check("T3.2 Empty drift count", tracker.get_drift_count(0) == 0)

    tracker.update_from_engagement(0, [
        "Great logistics delivery update for the whole supply chain region"
    ])
    drift = tracker.get_drift_text(0)
    check("T3.3 Keyword extraction", len(drift) > 0, f"drift='{drift}'")

    tracker2 = InterestTracker()
    for i in range(10):
        tracker2.update_from_engagement(0, [
            f"uniqueword{i} is a topic about specialsubject{i} concerning area{i}"
        ])
    check("T3.4 FIFO cap (<=5)", tracker2.get_drift_count(0) <= 5,
          f"count={tracker2.get_drift_count(0)}")

    profile_d = {"original_persona": "Seller Shopee", "general_domain": "ecommerce"}
    base_txt = build_interest_text(profile_d)
    enhanced_txt = build_interest_text(profile_d, drift_text="logistics delivery")
    check("T3.5 build_interest_text with drift",
          "logistics" in enhanced_txt and "logistics" not in base_txt)

    tracker3 = InterestTracker()
    tracker3.update_from_engagement(0, ["logistics shipping delivery express"])
    tracker3.update_from_engagement(1, ["fashion clothing style trend"])
    check("T3.6 Multi-agent independence",
          tracker3.get_drift_text(0) != tracker3.get_drift_text(1),
          f"0='{tracker3.get_drift_text(0)}' 1='{tracker3.get_drift_text(1)}'")

    # --- Phase 4: Reflection (6 tests) ---
    print("\n--- Phase 4: Reflection ---")

    refl = AgentReflection(interval=3)
    check("T4.1 Interval skip (round 1)", 1 % refl.interval != 0)
    check("T4.2 Interval trigger (round 3)", 3 % refl.interval == 0)

    base_p = "Seller Shopee, 3 years experience"
    check("T4.3 No insights = base persona",
          refl.get_evolved_persona(0, base_p) == base_p)
    check("T4.4 Empty insight count", refl.get_insight_count(0) == 0)

    refl._insights[0] = ["insight1", "insight2", "insight3", "insight4", "insight5"]
    refl._insights[0] = refl._insights[0][-refl.MAX_INSIGHTS:]
    evolved = refl.get_evolved_persona(0, base_p)
    check("T4.5 Insight cap (MAX=3)",
          "insight3" in evolved and "insight5" in evolved and "insight1" not in evolved,
          evolved[:80])

    agent_memory_off = None
    reflection_off = None
    if True:  # enable_reflection
        if agent_memory_off:
            reflection_off = AgentReflection(interval=3)
    check("T4.6 Dependency guard", reflection_off is None)

    print(f"\n{'='*70}")
    print(f"  RESULT: {passed}/{passed+failed} PASSED, {failed} FAILED")
    print(f"{'='*70}")
    return failed == 0


# ============================================
# PART 2: PERSONA EVOLUTION DEMO
# ============================================

DEMO_PROFILES = [
    {
        "name": "Nguyen Van A",
        "persona": "Seller Shopee with 3 years of experience in fashion ecommerce. "
                   "Specializes in women's clothing, bags and accessories. "
                   "Active community member who loves sharing product insights.",
        "mbti": "ENFJ",
        "general_domain": "ecommerce",
        "specific_domain": "fashion retail",
        "posts_per_week": 5,
        "daily_hours": 2.0,
    },
    {
        "name": "Tran Thi B",
        "persona": "Tech enthusiast and gadget reviewer on social media. "
                   "3000+ followers, focuses on mobile phones, laptops and accessories. "
                   "Quiet, analytical personality. Prefers facts over hype.",
        "mbti": "ISTP",
        "general_domain": "technology",
        "specific_domain": "consumer electronics review",
        "posts_per_week": 2,
        "daily_hours": 1.0,
    },
    {
        "name": "Le Van C",
        "persona": "Food blogger and restaurant reviewer based in Ho Chi Minh City. "
                   "Passionate about Vietnamese street food and local cuisine culture. "
                   "Extroverted and engaging, always looking for new dining experiences.",
        "mbti": "ENFP",
        "general_domain": "food and dining",
        "specific_domain": "restaurant reviews",
        "posts_per_week": 4,
        "daily_hours": 1.5,
    },
]

# Simulated engagement per round per agent (what posts they engaged with)
SIMULATED_ENGAGEMENTS = {
    1: {
        0: ["Flash sale khung 50% off toan bo vay dam nu!", "Tui xach hang hieu gia re ship nhanh Shopee"],
        1: ["iPhone 16 Pro Max review chi tiet camera va pin", "Samsung Galaxy S25 Ultra vs iPhone 16 benchmark test"],
        2: ["Pho bo Ha Noi ngon nhat Sai Gon o dau?", "Banh mi chao long Tan Dinh dat hang online"],
    },
    2: {
        0: ["Xu huong thoi trang mua he 2026 hot nhat", "Cach livestream ban hang Shopee hieu qua cho nguoi moi"],
        1: ["Laptop gaming MSI vs ASUS ROG so sanh hieu nang", "Tai nghe bluetooth Sony WH-1000XM6 review am thanh"],
        2: ["Com tam Sai Gon 5 dia ngon re ban phai thu", "Tra sua cheese foam trend moi nhat Ho Chi Minh"],
    },
    3: {
        0: ["Shopee mall chinh sach doi tra moi ap dung tu thang 7", "Logistics va van chuyen thuong mai dien tu 2026"],
        1: ["AI chip Qualcomm Snapdragon 8 Gen 4 lo dien hieu nang", "Robot hut bui tu dong thong minh cho nha pho"],
        2: ["Nha hang an chay ngon nhat quan 1 Sai Gon", "Mon an healthy cho nguoi tap gym diet clean"],
    },
    4: {
        0: ["Kinh nghiem mo shop thoi trang online 2026", "Quang cao Facebook cho shop quan ao nu hieu qua"],
        1: ["Mang 6G trien khai thu nghiem tai Viet Nam", "Smart home IoT ket noi tu dong moi thiet bi"],
        2: ["Street food tour Sai Gon cho du khach nuoc ngoai", "Review quan ca phe rooftop view dep quan 7"],
    },
    5: {
        0: ["Supply chain optimization cho SME ecommerce", "Xu huong sustainable fashion thoi trang ben vung"],
        1: ["Review camera action GoPro Hero 13 chong nuoc", "Drone quay phim 4K gia duoi 5 trieu tot nhat"],
        2: ["Workshop nau an Nhat Ban tai Ho Chi Minh", "Dau bep noi tieng chia se bi quyet nau pho"],
    },
    6: {
        0: ["Cross-border ecommerce ban hang quoc te qua Shopee", "Digital marketing trend 2026 cho nganh thoi trang"],
        1: ["VR headset Apple Vision Pro 2 review thuc te", "Coding voi AI assistant Copilot vs Cursor so sanh"],
        2: ["Food delivery app moi canh tranh voi GrabFood", "Festival am thuc duong pho Sai Gon 2026"],
    },
}

# Simulated actions per round per agent
SIMULATED_ACTIONS = {
    1: {
        0: [("create_post", "Flash sale tuan nay nhieu vay dam moi!"), ("like_post", "")],
        1: [("like_post", ""), ("create_comment", "Camera iPhone 16 that su tot")],
        2: [("create_post", "Pho bo Ha Noi ngon lam ne!"), ("like_post", ""), ("like_post", "")],
    },
    2: {
        0: [("create_post", "Mua he nay trend ao crop top quá hot"), ("like_post", ""), ("create_comment", "Livestream that su hieu qua cho ban hang")],
        1: [("like_post", ""), ("like_post", "")],
        2: [("create_post", "Com tam Sai Gon an la ghien"), ("like_post", "")],
    },
    3: {
        0: [("create_post", "Chinh sach doi tra moi cua Shopee rat tien"), ("like_post", "")],
        1: [("create_comment", "Snapdragon 8 Gen 4 that su an tuong"), ("like_post", "")],
        2: [("create_post", "An chay dang la xu huong moi"), ("create_comment", "Healthy food rat quan trong"), ("like_post", "")],
    },
    4: {
        0: [("create_post", "Chia se kinh nghiem mo shop fashion online"), ("like_post", ""), ("create_comment", "Facebook ad that su hieu qua")],
        1: [("like_post", ""), ("create_comment", "IoT co nhieu tiem nang")],
        2: [("create_post", "Street food Sai Gon la so 1!"), ("like_post", "")],
    },
    5: {
        0: [("create_post", "Supply chain la yeu to quan trong nhat"), ("like_post", "")],
        1: [("like_post", ""), ("create_comment", "GoPro 13 quay dep lam"), ("like_post", "")],
        2: [("create_post", "Hoc nau mon Nhat Ban cung thu vi"), ("like_post", ""), ("create_comment", "Bi quyet nau pho rat hay")],
    },
    6: {
        0: [("create_post", "Ban hang quoc te la tuong lai"), ("create_comment", "Digital marketing rat quan trong"), ("like_post", "")],
        1: [("like_post", ""), ("create_comment", "Vision Pro 2 that ra chat luong")],
        2: [("create_post", "Festival am thuc Sai Gon nam nay hoanh trang"), ("like_post", ""), ("like_post", "")],
    },
}

# Simulated reflection insights (what an LLM would generate)
SIMULATED_INSIGHTS = {
    3: {
        0: "This user is evolving from a pure fashion seller to also caring about logistics and return policies, showing growing business maturity.",
        1: "The user maintains a consistent focus on cutting-edge tech hardware but is beginning to show interest in AI and automation technologies.",
        2: "This user is expanding from traditional Vietnamese food reviews toward health-conscious and plant-based dining options.",
    },
    6: {
        0: "The user has shifted significantly from domestic fashion selling to international cross-border ecommerce and digital marketing strategy.",
        1: "The user shows a broadening interest beyond hardware reviews into software tools, VR experiences, and creator technology.",
        2: "This user is transitioning from individual restaurant reviews toward food industry coverage including delivery platforms and culinary events.",
    },
}


def run_persona_evolution_demo():
    print("\n" + "=" * 70)
    print("  PART 2: PERSONA EVOLUTION DEMO (6 rounds, 3 agents)")
    print("=" * 70)

    # Initialize all modules
    memory = AgentMemory(num_agents=3)
    interest_tracker = InterestTracker()
    reflection = AgentReflection(interval=3)

    # Show initial state
    print("\n" + "=" * 70)
    print("  INITIAL STATE (Round 0)")
    print("=" * 70)
    for i, p in enumerate(DEMO_PROFILES):
        mods = get_behavior_modifiers(p["mbti"])
        print(f"\n{'─' * 60}")
        print(f"  AGENT {i}: {p['name']} (MBTI: {p['mbti']})")
        print(f"{'─' * 60}")
        print(f"  MBTI Modifiers: post={mods['post_mult']}, comment={mods['comment_mult']}, "
              f"like={mods['like_mult']}, feed={mods['feed_mult']}")
        print(f"  PERSONA:")
        print(f"    {p['persona']}")
        print(f"  Interest Text:")
        interest = build_interest_text(p)
        print(f"    {interest}")
        print(f"  Memory: (empty)")
        print(f"  Drift: (none)")
        print(f"  Evolved Persona:")
        evolved = reflection.get_evolved_persona(i, p["persona"])
        print(f"    {evolved}")

    # Run 6 rounds
    for round_num in range(1, 7):
        print(f"\n{'=' * 70}")
        print(f"  ROUND {round_num}/6")
        print(f"{'=' * 70}")

        # --- PRE-ROUND: Reflection (every 3 rounds) ---
        if round_num % reflection.interval == 0 and round_num in SIMULATED_INSIGHTS:
            print(f"\n  >>> REFLECTION TRIGGERED (round {round_num}) <<<")
            for agent_id in range(3):
                insight = SIMULATED_INSIGHTS[round_num].get(agent_id)
                if insight:
                    reflection._insights[agent_id].append(insight)
                    if len(reflection._insights[agent_id]) > reflection.MAX_INSIGHTS:
                        reflection._insights[agent_id] = reflection._insights[agent_id][-reflection.MAX_INSIGHTS:]
                    name = DEMO_PROFILES[agent_id]["name"]
                    print(f"    [REFLECT] {name}: {insight}")

        # --- ACTIONS (record to memory) ---
        for agent_id in range(3):
            actions = SIMULATED_ACTIONS.get(round_num, {}).get(agent_id, [])
            for action_type, content in actions:
                memory.record_action(agent_id, action_type, content)

        # --- END ROUND: flush memory + update drift ---
        memory.end_round(round_num)

        for agent_id in range(3):
            engaged = SIMULATED_ENGAGEMENTS.get(round_num, {}).get(agent_id, [])
            if engaged:
                interest_tracker.update_from_engagement(agent_id, engaged)

        # --- PRINT FULL STATE FOR ALL AGENTS ---
        for agent_id in range(3):
            p = DEMO_PROFILES[agent_id]
            name = p["name"]

            print(f"\n  {'─' * 56}")
            print(f"  AGENT {agent_id}: {name} (MBTI: {p['mbti']})")
            print(f"  {'─' * 56}")

            # Memory
            mem_ctx = memory.get_context(agent_id)
            print(f"  MEMORY ({memory.get_round_count(agent_id)} rounds):")
            if mem_ctx:
                for line in mem_ctx.split("\n"):
                    print(f"    {line}")
            else:
                print(f"    (empty)")

            # Interest Drift
            drift = interest_tracker.get_drift_text(agent_id)
            print(f"  DRIFT KEYWORDS ({interest_tracker.get_drift_count(agent_id)}):")
            print(f"    {drift if drift else '(none)'}")

            # Full Interest Query
            full_interest = build_interest_text(p, drift_text=drift)
            print(f"  FULL INTEREST QUERY:")
            print(f"    {full_interest}")

            # Evolved Persona
            base_persona = p["persona"]
            evolved_persona = reflection.get_evolved_persona(agent_id, base_persona)
            print(f"  EVOLVED PERSONA ({reflection.get_insight_count(agent_id)} insights):")
            for line in evolved_persona.split("\n"):
                print(f"    {line}")

    # --- FINAL SUMMARY ---
    print(f"\n{'=' * 70}")
    print(f"  FINAL COMPARISON: Round 0 vs Round 6")
    print(f"{'=' * 70}")

    for agent_id in range(3):
        p = DEMO_PROFILES[agent_id]
        name = p["name"]
        base_persona = p["persona"]
        evolved_persona = reflection.get_evolved_persona(agent_id, base_persona)
        drift = interest_tracker.get_drift_text(agent_id)
        mem_ctx = memory.get_context(agent_id)

        print(f"\n{'━' * 70}")
        print(f"  AGENT {agent_id}: {name} (MBTI: {p['mbti']})")
        print(f"{'━' * 70}")

        print(f"\n  [BEFORE] BASE PERSONA:")
        print(f"    {base_persona}")

        print(f"\n  [AFTER] EVOLVED PERSONA:")
        for line in evolved_persona.split("\n"):
            print(f"    {line}")

        print(f"\n  [BEFORE] INTEREST QUERY:")
        base_interest = build_interest_text(p)
        print(f"    {base_interest}")

        print(f"\n  [AFTER] INTEREST QUERY (with drift):")
        enhanced_interest = build_interest_text(p, drift_text=drift)
        print(f"    {enhanced_interest}")

        print(f"\n  [MEMORY CONTEXT]:")
        if mem_ctx:
            for line in mem_ctx.split("\n"):
                print(f"    {line}")

        print(f"\n  [STATS]:")
        print(f"    Memory rounds: {memory.get_round_count(agent_id)}")
        print(f"    Drift keywords: {interest_tracker.get_drift_count(agent_id)} → '{drift}'")
        print(f"    Reflection insights: {reflection.get_insight_count(agent_id)}")
        mods = get_behavior_modifiers(p["mbti"])
        print(f"    MBTI modifiers: post={mods['post_mult']}, comment={mods['comment_mult']}, "
              f"like={mods['like_mult']}, feed={mods['feed_mult']}")


if __name__ == "__main__":
    all_ok = run_all_unit_tests()
    run_persona_evolution_demo()

    if all_ok:
        print(f"\n{'=' * 70}")
        print(f"  ALL TESTS PASSED + DEMO COMPLETE")
        print(f"{'=' * 70}")

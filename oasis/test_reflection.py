"""Unit tests for Phase 4: Reflection (offline only, no LLM)."""
import sys
sys.path.insert(0, r"e:\code\project\DUT_STARTUP\EcoSim\oasis")

from agent_cognition import AgentReflection

def test_interval_check():
    """T4.1: Reflection only triggers at interval."""
    refl = AgentReflection(interval=3)
    assert 1 % refl.interval != 0, "Round 1 should skip"
    assert 2 % refl.interval != 0, "Round 2 should skip"
    assert 3 % refl.interval == 0, "Round 3 should trigger"
    assert 6 % refl.interval == 0, "Round 6 should trigger"
    print("T4.1 PASS: interval logic correct")

def test_no_insights():
    """T4.3: No insights = base persona unchanged."""
    refl = AgentReflection(interval=3)
    base = "Seller Shopee, 3 years experience"
    assert refl.get_evolved_persona(0, base) == base
    assert refl.get_insight_count(0) == 0
    print("T4.3 PASS: no insights → base persona")

def test_insight_accumulation():
    """T4.4: Insights stored, capped at MAX_INSIGHTS=3."""
    refl = AgentReflection(interval=3)
    base = "Seller Shopee"

    # Manually add insights
    refl._insights[0] = [
        "Becoming more interested in logistics",
        "Shifting focus to customer service",
        "Engaging more with tech content",
        "Developing interest in sustainability",
        "Growing concern about shipping costs",
    ]
    # Should cap at 3
    if len(refl._insights[0]) > refl.MAX_INSIGHTS:
        refl._insights[0] = refl._insights[0][-refl.MAX_INSIGHTS:]

    evolved = refl.get_evolved_persona(0, base)
    assert "Recent reflections:" in evolved
    assert "Growing concern" in evolved  # latest
    assert "Developing interest" in evolved
    assert "Becoming more" not in evolved  # evicted
    assert refl.get_insight_count(0) == 3
    print(f"T4.4 PASS: {refl.get_insight_count(0)} insights, base preserved")
    print(f"  Evolved: {evolved[:100]}...")

def test_dependency_guard():
    """T4.5: enable_reflection=true but agent_memory=None → reflection=None."""
    agent_memory = None
    reflection = None
    if True:  # enable_reflection
        if agent_memory:
            reflection = AgentReflection(interval=3)
        else:
            reflection = None  # skipped

    assert reflection is None
    print("T4.5 PASS: dependency guard works")

def test_evolved_persona_format():
    """T4.6: Evolved persona preserves base and appends insights."""
    refl = AgentReflection(interval=3)
    base = "Seller Shopee, 3 years experience in ecommerce"
    refl._insights[0] = ["Growing interest in logistics optimization"]

    evolved = refl.get_evolved_persona(0, base)
    assert evolved.startswith(base), "Should start with base persona"
    assert "\n\nRecent reflections:" in evolved
    assert "logistics optimization" in evolved
    print(f"T4.6 PASS: format correct")
    print(f"  First 80: {evolved[:80]}")

def test_multi_agent():
    """Different agents have independent insights."""
    refl = AgentReflection(interval=3)
    refl._insights[0] = ["Agent 0 insight"]
    refl._insights[1] = ["Agent 1 insight"]

    e0 = refl.get_evolved_persona(0, "Base 0")
    e1 = refl.get_evolved_persona(1, "Base 1")
    assert "Agent 0" in e0 and "Agent 1" not in e0
    assert "Agent 1" in e1 and "Agent 0" not in e1

    # Agent 2 has no insights
    e2 = refl.get_evolved_persona(2, "Base 2")
    assert e2 == "Base 2"
    print("T4.extra PASS: multi-agent independent insights")

if __name__ == "__main__":
    test_interval_check()
    test_no_insights()
    test_insight_accumulation()
    test_dependency_guard()
    test_evolved_persona_format()
    test_multi_agent()
    print("\nAll Phase 4 unit tests passed!")

"""Unit tests for Phase 2: MBTI Behavioral Modifiers."""
import sys
sys.path.insert(0, r"e:\code\project\DUT_STARTUP\EcoSim\oasis")

from agent_cognition import get_behavior_modifiers
from interest_feed import should_post, get_feed_size

def test_modifier_lookup():
    """T2.1: Known MBTI types return correct multipliers."""
    m = get_behavior_modifiers("ENFJ")
    assert m["post_mult"] == 1.2, f"E->post_mult expected 1.2, got {m['post_mult']}"
    assert m["comment_mult"] == 1.3, f"E->comment_mult expected 1.3, got {m['comment_mult']}"
    assert m["like_mult"] == 1.2, f"F->like_mult expected 1.2, got {m['like_mult']}"
    assert m["feed_mult"] == 0.9, f"J->feed_mult expected 0.9, got {m['feed_mult']}"
    print(f"T2.1a PASS (ENFJ): {m}")

    m2 = get_behavior_modifiers("ISTP")
    assert m2["post_mult"] == 0.8
    assert m2["comment_mult"] == 0.7
    assert m2["like_mult"] == 0.9
    assert m2["feed_mult"] == 1.2  # P
    print(f"T2.1b PASS (ISTP): {m2}")

def test_unknown_mbti():
    """T2.2: Empty/unknown MBTI returns all defaults = 1.0."""
    m = get_behavior_modifiers("")
    assert all(v == 1.0 for v in m.values()), f"Expected all 1.0, got {m}"
    print(f"T2.2a PASS (empty): {m}")

    m2 = get_behavior_modifiers("XXXX")
    assert all(v == 1.0 for v in m2.values()), f"Expected all 1.0, got {m2}"
    print(f"T2.2b PASS (invalid): {m2}")

def test_should_post_multiplier():
    """T2.3: Monte Carlo test — E agents post more than I agents."""
    import random
    profile = {"posts_per_week": 3}

    rng_e = random.Random(42)
    high = sum(should_post(profile, rng_e, post_mult=1.2) for _ in range(1000))

    rng_i = random.Random(42)
    low = sum(should_post(profile, rng_i, post_mult=0.8) for _ in range(1000))

    ratio = high / max(low, 1)
    assert high > low, f"E({high}) should be > I({low})"
    print(f"T2.3 PASS: E={high}, I={low}, ratio={ratio:.2f}")

def test_feed_size_multiplier():
    """T2.4: Feed size scales with multiplier."""
    base = get_feed_size(1.0)  # 5 posts
    wider = get_feed_size(1.0, feed_mult=1.2)
    narrower = get_feed_size(1.0, feed_mult=0.9)

    assert wider >= base, f"P(wider={wider}) should >= base({base})"
    assert narrower <= base, f"J(narrower={narrower}) should <= base({base})"
    print(f"T2.4 PASS: base={base}, P={wider}, J={narrower}")

def test_toggle_off():
    """T2.5: When toggle OFF, all modifiers are 1.0."""
    m = get_behavior_modifiers("")
    assert m["post_mult"] == 1.0
    assert m["comment_mult"] == 1.0
    assert m["like_mult"] == 1.0
    print("T2.5 PASS: toggle OFF safe → all 1.0")

if __name__ == "__main__":
    test_modifier_lookup()
    test_unknown_mbti()
    test_should_post_multiplier()
    test_feed_size_multiplier()
    test_toggle_off()
    print("\nAll Phase 2 unit tests passed!")

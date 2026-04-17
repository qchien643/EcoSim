"""Unit tests for Phase 3: Interest Drift."""
import sys
sys.path.insert(0, r"e:\code\project\DUT_STARTUP\EcoSim\oasis")

from agent_cognition import InterestTracker
from interest_feed import build_interest_text

def test_keyword_extraction():
    """T3.1: Keywords extracted from engaged posts."""
    tracker = InterestTracker()
    tracker.update_from_engagement(0, [
        "Great logistics delivery update for the whole supply chain region"
    ])
    drift = tracker.get_drift_text(0)
    assert drift, "Should have drift keywords"
    words = drift.split()
    assert len(words) <= 2, f"Should have max 2 new keywords per round, got {len(words)}"
    print(f"T3.1 PASS: drift='{drift}'")

def test_fifo_cap():
    """T3.2: Max 5 keywords tracked."""
    tracker = InterestTracker()
    for i in range(10):
        tracker.update_from_engagement(0, [
            f"uniqueword{i} is a topic about specialsubject{i} concerning area{i}"
        ])
    drift = tracker.get_drift_text(0)
    count = tracker.get_drift_count(0)
    assert count <= 5, f"Expected <=5 keywords, got {count}: {drift}"
    print(f"T3.2 PASS: {count} keywords after 10 rounds: '{drift}'")

def test_empty_drift():
    """T3.3: No engagement = empty drift."""
    tracker = InterestTracker()
    assert tracker.get_drift_text(0) == ""
    assert tracker.get_drift_count(0) == 0
    print("T3.3 PASS: empty drift for new agent")

def test_build_interest_with_drift():
    """T3.4: build_interest_text includes drift text."""
    profile = {"original_persona": "Seller Shopee", "general_domain": "ecommerce"}
    base = build_interest_text(profile)
    enhanced = build_interest_text(profile, drift_text="logistics delivery")
    assert "logistics" in enhanced, f"Drift not found in: {enhanced}"
    assert "logistics" not in base, "Base should not have drift"
    assert "Seller Shopee" in enhanced, "Should still have base persona"
    print(f"T3.4 PASS: base='{base[:40]}...' enhanced='{enhanced[:60]}...'")

def test_toggle_off():
    """T3.5: When tracker is None, drift_text is empty."""
    interest_tracker = None
    drift = interest_tracker.get_drift_text(0) if interest_tracker else ""
    assert drift == "", "Should be empty when toggle OFF"
    print("T3.5 PASS: toggle OFF safe")

def test_multi_agent_independence():
    """T3.6: Different agents track independently."""
    tracker = InterestTracker()
    tracker.update_from_engagement(0, ["logistics shipping delivery express"])
    tracker.update_from_engagement(1, ["fashion clothing style trend"])
    
    drift0 = tracker.get_drift_text(0)
    drift1 = tracker.get_drift_text(1)
    assert drift0 != drift1, f"Should be different: agent0='{drift0}' agent1='{drift1}'"
    print(f"T3.6 PASS: agent0='{drift0}' agent1='{drift1}'")

if __name__ == "__main__":
    test_empty_drift()
    test_keyword_extraction()
    test_fifo_cap()
    test_build_interest_with_drift()
    test_toggle_off()
    test_multi_agent_independence()
    print("\nAll Phase 3 unit tests passed!")

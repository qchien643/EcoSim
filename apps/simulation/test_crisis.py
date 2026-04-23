"""
Crisis Injection Unit Tests
============================
Tests for CrisisEvent, CrisisEngine, and InterestVectorTracker.inject_crisis_interests.

Usage:
    cd EcoSim/oasis
    .venv\\Scripts\\python.exe test_crisis.py
"""
import json
import os
import sys
import tempfile

# Add oasis to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crisis_engine import CrisisEvent, CrisisEngine, CRISIS_TEMPLATES

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}")
        if detail:
            print(f"     → {detail}")


# ================================================================
# TEST 1: CrisisEvent Construction & Defaults
# ================================================================
print("\n" + "═" * 60)
print("  TEST 1: CrisisEvent Construction & Defaults")
print("═" * 60)

# Basic construction
e1 = CrisisEvent(trigger_round=3, crisis_type="scandal", title="Data Leak",
                 description="User data was leaked online")
check("Basic construction", e1.trigger_round == 3)
check("Type set", e1.crisis_type == "scandal")
check("Title set", e1.title == "Data Leak")
check("ID generated", e1.crisis_id.startswith("crisis_") and len(e1.crisis_id) > 10)
check("Not injected initially", e1.injected == False)

# Template defaults fill in
check("Severity from template (scandal=0.8)", e1.severity == 0.8,
      f"got {e1.severity}")
check("Affected domains from template", "trust" in e1.affected_domains and "privacy" in e1.affected_domains)
check("Interest keywords from template", len(e1.interest_keywords) > 0)

# Custom type doesn't override
e2 = CrisisEvent(trigger_round=1, crisis_type="custom", title="Test",
                 severity=0.3, affected_domains=["x"])
check("Custom severity preserved", e2.severity == 0.3)
check("Custom domains preserved", e2.affected_domains == ["x"])

# Severity clamping
e3 = CrisisEvent(trigger_round=1, severity=1.5)
check("Severity clamped to 1.0", e3.severity == 1.0)
e4 = CrisisEvent(trigger_round=1, severity=-0.5)
check("Severity clamped to 0.0", e4.severity == 0.0)

# Serialization roundtrip
d = e1.to_dict()
check("to_dict returns dict", isinstance(d, dict))
check("to_dict has all fields", all(k in d for k in ["crisis_id", "trigger_round", "crisis_type"]))
e1_back = CrisisEvent.from_dict(d)
check("from_dict roundtrip", e1_back.title == "Data Leak" and e1_back.trigger_round == 3)


# ================================================================
# TEST 2: CrisisEngine Scheduling
# ================================================================
print("\n" + "═" * 60)
print("  TEST 2: CrisisEngine Scheduling")
print("═" * 60)

events = [
    CrisisEvent(trigger_round=2, title="Event A"),
    CrisisEvent(trigger_round=2, title="Event B"),
    CrisisEvent(trigger_round=5, title="Event C"),
]
engine = CrisisEngine(events)

check("Engine has 3 events", len(engine.events) == 3)
check("Has pending events", engine.has_pending_events())

# Round 1: nothing triggers
r1 = engine.get_events_for_round(1)
check("Round 1: no events", len(r1) == 0)

# Round 2: two events trigger
r2 = engine.get_events_for_round(2)
check("Round 2: 2 events", len(r2) == 2)
check("Round 2: Event A", r2[0].title == "Event A")
check("Round 2: Event B", r2[1].title == "Event B")
check("Events marked as injected", r2[0].injected and r2[1].injected)

# Round 2 again: no repeat
r2_again = engine.get_events_for_round(2)
check("Round 2 repeat: no events (already injected)", len(r2_again) == 0)

# Round 5: Event C
r5 = engine.get_events_for_round(5)
check("Round 5: 1 event", len(r5) == 1)
check("Round 5: Event C", r5[0].title == "Event C")

# Triggered log
log = engine.get_crisis_log()
check("Triggered log has 3 entries", len(log) == 3)
check("Log entry has round", log[0]["round"] == 2)

# No more pending
check("No more pending events", not engine.has_pending_events())

# Summary
summary = engine.get_summary()
check("Summary total=3, triggered=3, pending=0",
      summary["total_events"] == 3 and summary["triggered"] == 3 and summary["pending"] == 0)


# ================================================================
# TEST 3: CrisisEngine Dynamic Add
# ================================================================
print("\n" + "═" * 60)
print("  TEST 3: Dynamic Event Addition (Real-time)")
print("═" * 60)

engine2 = CrisisEngine()
check("Empty engine", len(engine2.events) == 0)

engine2.add_event(CrisisEvent(trigger_round=3, title="Live Event"))
check("1 event after add", len(engine2.events) == 1)
check("Has pending", engine2.has_pending_events())

r3 = engine2.get_events_for_round(3)
check("Round 3 triggers live event", len(r3) == 1 and r3[0].title == "Live Event")


# ================================================================
# TEST 4: File-based IPC (pending_crisis.json)
# ================================================================
print("\n" + "═" * 60)
print("  TEST 4: File-based IPC (pending_crisis.json)")
print("═" * 60)

with tempfile.TemporaryDirectory() as tmpdir:
    engine3 = CrisisEngine()

    # No file → empty result
    loaded = engine3.load_pending_events(tmpdir, 5)
    check("No file: empty result", len(loaded) == 0)

    # Write single event
    pending = {"crisis_type": "price_change", "title": "Price Hike",
               "description": "30% increase", "severity": 0.7}
    with open(os.path.join(tmpdir, "pending_crisis.json"), "w") as f:
        json.dump(pending, f)

    loaded = engine3.load_pending_events(tmpdir, 5)
    check("Single event loaded", len(loaded) == 1)
    check("Title correct", loaded[0].title == "Price Hike")
    check("Trigger round set to current", loaded[0].trigger_round == 5)
    check("File deleted after read", not os.path.exists(os.path.join(tmpdir, "pending_crisis.json")))
    check("Event added to engine", len(engine3.events) == 1)

    # Write list of events
    pending_list = [
        {"crisis_type": "scandal", "title": "Scandal 1"},
        {"crisis_type": "news", "title": "News 1"},
    ]
    with open(os.path.join(tmpdir, "pending_crisis.json"), "w") as f:
        json.dump(pending_list, f)

    loaded2 = engine3.load_pending_events(tmpdir, 6)
    check("List of 2 events loaded", len(loaded2) == 2)
    check("Both trigger at round 6", all(e.trigger_round == 6 for e in loaded2))
    check("Engine now has 3 events total", len(engine3.events) == 3)


# ================================================================
# TEST 5: Interest Perturbation
# ================================================================
print("\n" + "═" * 60)
print("  TEST 5: Interest Perturbation Generation")
print("═" * 60)

e_perturb = CrisisEvent(trigger_round=1, crisis_type="scandal",
                         title="Major Data Breach", severity=0.9)
engine4 = CrisisEngine([e_perturb])
perturbation = engine4.get_interest_perturbation(e_perturb)

check("Has keywords", len(perturbation["keywords"]) > 0)
check("Has weight_boost", 0.0 < perturbation["weight_boost"] <= 1.0,
      f"got {perturbation['weight_boost']}")
check("High severity → high boost", perturbation["weight_boost"] > 0.8)
check("Has decay_factor", 0.0 <= perturbation["decay_factor"] <= 0.5)
check("Has source tag", perturbation["source"].startswith("crisis:"))
check("Title words in keywords", any("Major" in kw or "Data" in kw or "Breach" in kw
                                       for kw in perturbation["keywords"]))


# ================================================================
# TEST 6: Persona Modifier
# ================================================================
print("\n" + "═" * 60)
print("  TEST 6: Persona Modifier Generation")
print("═" * 60)

e_mod = CrisisEvent(trigger_round=1, title="Server Outage",
                    description="Platform went down for 3 hours",
                    severity=0.8, sentiment_shift="negative")
modifier = engine4.get_persona_modifier(e_mod)

check("Modifier is non-empty string", isinstance(modifier, str) and len(modifier) > 20)
check("Contains event title", "Server Outage" in modifier)
check("Contains description", "3 hours" in modifier)
check("High severity → 'extremely concerned'", "extremely concerned" in modifier)
check("Negative sentiment → 'worried'", "worried" in modifier)

# Test positive sentiment
e_pos = CrisisEvent(trigger_round=1, title="Big Sale",
                    severity=0.3, sentiment_shift="positive")
mod_pos = engine4.get_persona_modifier(e_pos)
check("Positive → 'excited'", "excited" in mod_pos)
check("Low severity → 'has heard about'", "has heard about" in mod_pos)


# ================================================================
# TEST 7: InterestVectorTracker.inject_crisis_interests
# ================================================================
print("\n" + "═" * 60)
print("  TEST 7: InterestVectorTracker.inject_crisis_interests")
print("═" * 60)

from agent_cognition import InterestVectorTracker

tracker = InterestVectorTracker()

# Initialize a test agent
test_profile = {
    "mbti": "ENFP",
    "specific_domain": "Technology",
    "general_domain": "Science",
    "persona": "A tech enthusiast who loves gadgets and innovation.",
}
tracker.initialize_agent(0, test_profile)

# Check initial state
initial_interests = tracker.get_top_interests(0, 10)
check("Agent has initial interests", len(initial_interests) > 0)
initial_count = len(initial_interests)

# Get initial weights
initial_weights = {kw: w for kw, w in initial_interests}

# Inject crisis
perturbation = {
    "keywords": ["data breach", "security alert", "privacy concern"],
    "weight_boost": 0.8,
    "decay_factor": 0.2,
    "source": "crisis:test_001",
}
tracker.inject_crisis_interests(0, perturbation, round_num=3)

# Check post-injection
post_interests = tracker.get_top_interests(0, 20)
post_dict = {kw: w for kw, w in post_interests}

check("Crisis keywords injected", "data breach" in post_dict)
check("All 3 crisis keywords present",
      all(kw in post_dict for kw in ["data breach", "security alert", "privacy concern"]))
check("Crisis keywords have high weight", post_dict.get("data breach", 0) >= 0.7,
      f"got {post_dict.get('data breach', 0)}")

# Verify profile interests were NOT removed (protected)
profile_kws = {"technology", "science"}
for kw in profile_kws:
    if kw in initial_weights:
        check(f"Profile interest '{kw}' preserved", kw in post_dict,
              f"'{kw}' was removed!")

# Verify history was updated
history = tracker.get_history(0)
check("History has extra snapshot", len(history) >= 2)


# ================================================================
# TEST 8: All Crisis Templates
# ================================================================
print("\n" + "═" * 60)
print("  TEST 8: All Crisis Templates")
print("═" * 60)

for ctype, template in CRISIS_TEMPLATES.items():
    e = CrisisEvent(trigger_round=1, crisis_type=ctype, title=f"Test {ctype}")
    check(f"Template '{ctype}' creates valid event",
          e.crisis_type == ctype and e.severity > 0)


# ================================================================
# SUMMARY
# ================================================================
print(f"\n{'═' * 60}")
print(f"  RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
print(f"{'═' * 60}")

if failed == 0:
    print("  ✅ ALL TESTS PASSED!")
else:
    print(f"  ⚠️  {failed} test(s) failed")

sys.exit(0 if failed == 0 else 1)

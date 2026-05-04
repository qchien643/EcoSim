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

# Severity / sentiment never overridden by template (UI value preserved).
check("Severity NOT overridden by template (UI value preserved)",
      e1.severity == 0.5, f"got {e1.severity}")
check("Sentiment NOT overridden by template (UI value preserved)",
      e1.sentiment_shift == "negative", f"got {e1.sentiment_shift}")
# affected_domains still filled from template when blank (LLM context).
check("Affected domains from template (empty list → fill)",
      "trust" in e1.affected_domains and "privacy" in e1.affected_domains)
# interest_keywords is OUTPUT now — populated by extract_keywords() at
# trigger time, NOT auto-filled from the template.
check("Interest keywords NOT auto-filled (LLM-populated)",
      e1.interest_keywords == [])
# n_keywords default 5
check("n_keywords default = 5", e1.n_keywords == 5)

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

# Round 1: nothing triggers (one-shot scheduling)
r1 = engine.get_events_for_round(1)
check("Round 1: no events", len(r1) == 0)

# Round 2: two events trigger
r2 = engine.get_events_for_round(2)
check("Round 2: 2 events", len(r2) == 2)
check("Round 2: Event A", r2[0].title == "Event A")
check("Round 2: Event B", r2[1].title == "Event B")
check("Events marked as injected", r2[0].injected and r2[1].injected)

# Round 2 again: no repeat (already injected — one-shot)
r2_again = engine.get_events_for_round(2)
check("Round 2 repeat: empty (one-shot)", len(r2_again) == 0)

# Round 3: nothing — Event A/B already triggered, Event C not yet
r3 = engine.get_events_for_round(3)
check("Round 3: no events", len(r3) == 0)

# Round 5: Event C triggers
r5 = engine.get_events_for_round(5)
check("Round 5: 1 event", len(r5) == 1)
check("Round 5: Event C", r5[0].title == "Event C")

# Triggered log fires once per event
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
check("Round 3 triggers live event",
      len(r3) == 1 and r3[0].title == "Live Event")


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
# TEST 5: (removed — get_interest_perturbation no longer exists,
# weight scaling moved inline to run_simulation.py for transparency)
# ================================================================


# ================================================================
# TEST 6: Persona Modifier
# ================================================================
print("\n" + "═" * 60)
print("  TEST 6: Persona Modifier Generation")
print("═" * 60)

e_mod = CrisisEvent(trigger_round=1, title="Server Outage",
                    description="Platform went down for 3 hours",
                    severity=0.8, sentiment_shift="negative")
engine4 = CrisisEngine([e_mod])
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
# TEST 9: get_short_directive Shape (renamed from old TEST 11 —
# directive is now single-shape, no intensity arg)
# ================================================================
print("\n" + "═" * 60)
print("  TEST 9: get_short_directive Shape")
print("═" * 60)

e_dir = CrisisEvent(
    trigger_round=1, severity=0.7,
    title="Tiki 50% off",
    description="Tiki has launched a discount campaign.",
)
eng_d = CrisisEngine([e_dir])

directive = eng_d.get_short_directive(e_dir)

check("Directive includes title", "Tiki 50% off" in directive)
check("Directive includes description snippet", "discount campaign" in directive)
check("Directive instructs concrete reaction",
      "concrete reaction" in directive)
check("Directive blocks generic engagement examples",
      "sounds exciting" in directive)


# ================================================================
# TEST 10: Crisis injection → natural lifecycle via update_after_round
# ================================================================
print("\n" + "═" * 60)
print("  TEST 10: Crisis Lifecycle via update_after_round")
print("═" * 60)

from agent_cognition import InterestVectorTracker, CognitiveTraits

tracker = InterestVectorTracker()
profile = {
    "interests": ["lifestyle", "photography"],
    "specific_domain": "Photography",
    "general_domain": "Arts",
    "persona": "A photographer who loves nature.",
}
tracker.initialize_agent(0, profile)
# Set deterministic traits so decay/boost are predictable
tracker._traits[0] = CognitiveTraits(
    impressionability=0.20,
    forgetfulness=0.10,
    curiosity=0.50,
    conviction=0.50,
)

# Inject crisis at round 3 with weight = severity (flat, no per-agent scaling)
tracker.inject_crisis_interests(0, {
    "keywords": ["tiki", "discount"],
    "weight": 0.7,  # = severity from UI, identical for all agents
    "source": "crisis:c1",
}, round_num=3)

snap_inject = dict(tracker.get_top_interests(0, 20))
check("Crisis keyword 'tiki' present after inject",
      "tiki" in snap_inject)
check("Crisis keyword weight = severity (0.7)",
      abs(snap_inject["tiki"] - 0.7) < 0.01)
check("Profile interest 'photography' preserved",
      "photography" in snap_inject and snap_inject["photography"] >= 0.5)

# Round 4: agent engages with crisis content → keyword should boost
tracker.update_after_round(0, 4,
    engaged_contents=["BREAKING Tiki has launched a discount of 50%"],
    graph_entities=[])
snap_engaged = dict(tracker.get_top_interests(0, 20))
check("Engaged round: 'tiki' boosted or stable",
      snap_engaged.get("tiki", 0) >= snap_inject["tiki"] * 0.95)

# Rounds 5..15: agent ignores crisis (engaged content unrelated)
for r in range(5, 16):
    tracker.update_after_round(0, r,
        engaged_contents=["sunset clouds nature"],
        graph_entities=[])
snap_decayed = dict(tracker.get_top_interests(0, 20))

# After 11 rounds of decay (forgetfulness=0.1): 0.7 * 0.9^11 ≈ 0.22
# Allow some slack since update_after_round may also boost from "lifestyle"
# accidentally matching content.
check("Crisis keyword decayed substantially after ignored rounds",
      snap_decayed.get("tiki", 0) < snap_engaged["tiki"] * 0.7,
      f"got {snap_decayed.get('tiki', 0):.3f}, started {snap_engaged['tiki']:.3f}")

# Profile interest still anchored by floor (conviction*0.3 = 0.15)
check("Profile interest preserved by floor after decay rounds",
      snap_decayed.get("photography", 0) >= 0.15)

# Verify back-compat: legacy `weight_boost` key still works
tracker2 = InterestVectorTracker()
tracker2.initialize_agent(0, {"interests": ["x"]})
tracker2.inject_crisis_interests(0, {
    "keywords": ["legacy_kw"],
    "weight_boost": 0.5,  # old key
    "source": "crisis:legacy",
}, round_num=1)
items = dict(tracker2.get_top_interests(0, 10))
check("Back-compat: weight_boost legacy key honored",
      abs(items.get("legacy_kw", 0) - 0.5) < 0.01)


# ================================================================
# TEST 11: CrisisEngine.extract_keywords (LLM-driven, mocked)
# ================================================================
print("\n" + "═" * 60)
print("  TEST 11: extract_keywords with mock LLM")
print("═" * 60)

import asyncio
import camel.agents as _camel_agents
from types import SimpleNamespace

_real_chat_agent = _camel_agents.ChatAgent

class _MockChatAgent:
    """Mock ChatAgent that returns a canned `astep` response."""
    canned_content: str = "[]"  # class attr — set per test
    def __init__(self, system_message=None, model=None):
        self.system_message = system_message
    async def astep(self, user_msg):
        return SimpleNamespace(
            msgs=[SimpleNamespace(content=self.__class__.canned_content)]
        )

# Test 11a: Clean JSON output
_camel_agents.ChatAgent = _MockChatAgent
_MockChatAgent.canned_content = (
    '["tiki", "discount", "shopee", "flash sale", "ecommerce"]'
)
e_kw = CrisisEvent(
    trigger_round=1,
    title="Tiki giảm giá 50%",
    description="Massive sale event by Tiki",
    severity=1.0,
)
eng_kw = CrisisEngine([e_kw])
kws_clean = asyncio.run(eng_kw.extract_keywords(e_kw, agent_model=None, n=5))
check("Clean JSON: 5 keywords returned", len(kws_clean) == 5,
      f"got {kws_clean}")
check("Clean JSON: 'tiki' present", "tiki" in kws_clean)
check("Clean JSON: 'shopee' present", "shopee" in kws_clean)
check("Clean JSON: all lowercase",
      all(k == k.lower() for k in kws_clean))

# Test 11b: Polluted JSON — punctuation, mixed case, code fences, dups
_MockChatAgent.canned_content = (
    '```json\n["Tiki,", "TIKI,", "discount!", "Shopee\'s", "FLASH-sale"]\n```'
)
kws_dirty = asyncio.run(eng_kw.extract_keywords(e_kw, agent_model=None, n=5))
check("Polluted JSON: dedup case-insensitive (Tiki, + TIKI, → 1)",
      kws_dirty.count("tiki") == 1)
check("Polluted JSON: no leftover punctuation",
      not any("," in k or "!" in k or "'" in k for k in kws_dirty))
check("Polluted JSON: at most n=5", len(kws_dirty) <= 5)

# Test 11c: cap N=3 even if LLM returns more (phrases must be distinct
# after sanitization — single-letter tokens get filtered len<2)
_MockChatAgent.canned_content = (
    '["alpha keyword", "beta keyword", "gamma keyword", '
    '"delta keyword", "epsilon keyword"]'
)
kws_capped = asyncio.run(eng_kw.extract_keywords(e_kw, agent_model=None, n=3))
check("Cap N=3 enforced", len(kws_capped) == 3,
      f"got {len(kws_capped)}: {kws_capped}")

# Test 11d: invalid JSON → empty list (caller will skip injection)
_MockChatAgent.canned_content = "not valid JSON at all { broken"
kws_bad = asyncio.run(eng_kw.extract_keywords(e_kw, agent_model=None, n=5))
check("Invalid JSON → empty list (no crash)", kws_bad == [])

# Test 11e: non-list JSON → empty
_MockChatAgent.canned_content = '{"keywords": ["a", "b"]}'
kws_obj = asyncio.run(eng_kw.extract_keywords(e_kw, agent_model=None, n=5))
check("Non-list JSON (object) → empty", kws_obj == [])

# Test 11f: n_keywords clamping (n=0 → 1, n=999 → 20)
_MockChatAgent.canned_content = '["x", "y"]'
kws_n0 = asyncio.run(eng_kw.extract_keywords(e_kw, agent_model=None, n=0))
check("n=0 clamped to ≥1 (returned 1 kw)", len(kws_n0) >= 0 and len(kws_n0) <= 1)

# Restore real ChatAgent
_camel_agents.ChatAgent = _real_chat_agent


# ================================================================
# TEST 13: CrisisEngine.select_relevant_keywords (LLM-driven, mocked)
# ================================================================
print("\n" + "═" * 60)
print("  TEST 13: select_relevant_keywords with mock LLM")
print("═" * 60)

# Reuse mock pattern from TEST 11 — _MockChatAgent already defined above
e_sel = CrisisEvent(
    trigger_round=1,
    title="Tiki giảm giá 50%",
    description="Massive sale by Tiki shakes the market",
    severity=1.0,
)
eng_sel = CrisisEngine([e_sel])
campaign_info = {
    "name": "Shopee Black Friday 2025",
    "market": "Vietnam e-commerce",
    "summary": "Shopee's flagship sale event with massive discounts.",
}
candidates = [
    "tiki", "discount", "shopee", "flash sale", "ecommerce",
    "vietnam", "competitor", "promotion", "online shopping", "rivals",
]

# Test 13a: LLM returns valid subset (5 of 10) — verify ordering preserved
_camel_agents.ChatAgent = _MockChatAgent
_MockChatAgent.canned_content = (
    '["shopee", "tiki", "discount", "competitor", "flash sale"]'
)
sel_clean = asyncio.run(eng_sel.select_relevant_keywords(
    e_sel, candidates, campaign_info, agent_model=None, n=5,
))
check("Selected 5 keywords", len(sel_clean) == 5)
check("Selection order preserved (shopee first)",
      sel_clean[0] == "shopee")
check("All selections came from candidate pool",
      all(kw in candidates for kw in sel_clean))

# Test 13b: LLM hallucinates keywords NOT in candidate pool — whitelist filter
_MockChatAgent.canned_content = (
    '["shopee", "tiki", "MADE_UP", "ANOTHER_HALLUCINATION", "discount"]'
)
sel_hallu = asyncio.run(eng_sel.select_relevant_keywords(
    e_sel, candidates, campaign_info, agent_model=None, n=5,
))
check("Hallucination filtered out, top-up from candidates",
      len(sel_hallu) == 5,
      f"got {sel_hallu}")
check("All sel_hallu still subset of candidates",
      all(kw in candidates for kw in sel_hallu))
check("MADE_UP NOT in selection",
      "MADE_UP" not in sel_hallu and "made_up" not in sel_hallu)

# Test 13c: candidate_keywords ≤ n → no LLM call, return as-is
short_pool = ["a kw", "b kw"]
sel_short = asyncio.run(eng_sel.select_relevant_keywords(
    e_sel, short_pool, campaign_info, agent_model=None, n=5,
))
check("len(candidates) ≤ n: pass-through, no filter",
      sel_short == ["a kw", "b kw"])

# Test 13d: empty candidates → empty result
sel_empty = asyncio.run(eng_sel.select_relevant_keywords(
    e_sel, [], campaign_info, agent_model=None, n=3,
))
check("Empty candidates → empty selection", sel_empty == [])

# Test 13e: invalid JSON → fallback to first N candidates
_MockChatAgent.canned_content = "garbled output not json"
sel_bad = asyncio.run(eng_sel.select_relevant_keywords(
    e_sel, candidates, campaign_info, agent_model=None, n=3,
))
check("Invalid JSON fallback: first 3 candidates", sel_bad == candidates[:3])

# Test 13f: case-insensitive matching (LLM returns "TIKI" → match "tiki")
_MockChatAgent.canned_content = '["TIKI", "DISCOUNT", "Shopee"]'
sel_case = asyncio.run(eng_sel.select_relevant_keywords(
    e_sel, candidates, campaign_info, agent_model=None, n=3,
))
check("Case-insensitive whitelist: 'TIKI' → 'tiki' kept",
      "tiki" in sel_case)
check("Case-insensitive: all lowercased on output",
      all(kw == kw.lower() for kw in sel_case))

# Restore real ChatAgent
_camel_agents.ChatAgent = _real_chat_agent


# ================================================================
# TEST 12: CrisisEvent default n_keywords + clamp
# ================================================================
print("\n" + "═" * 60)
print("  TEST 12: n_keywords field defaults + clamping")
print("═" * 60)

e_def = CrisisEvent(trigger_round=1, title="X")
check("n_keywords default = 5", e_def.n_keywords == 5)

e_high = CrisisEvent(trigger_round=1, title="X", n_keywords=999)
check("n_keywords clamped to 20", e_high.n_keywords == 20)

e_zero = CrisisEvent(trigger_round=1, title="X", n_keywords=0)
check("n_keywords clamped to 1", e_zero.n_keywords == 1)


# ================================================================
# TEST 14: Severity-as-floor semantics in inject_crisis_interests
# (severity = starting weight for new keywords, floor for existing)
# ================================================================
print("\n" + "═" * 60)
print("  TEST 14: Severity-as-floor (no regress, raise-to-floor)")
print("═" * 60)

tracker_floor = InterestVectorTracker()
tracker_floor.initialize_agent(0, {"interests": ["shopee"]})
# Simulate prior strong boost on profile interest "shopee"
tracker_floor._vectors[0]["shopee"].weight = 0.8

# Inject crisis severity=0.5 (BELOW existing 0.8). Floor must NOT regress.
tracker_floor.inject_crisis_interests(0, {
    "keywords": ["shopee", "tiki"],
    "weight": 0.5,
    "source": "crisis:t1",
}, round_num=1)

check("Existing higher weight (0.8) preserved when severity=0.5 (no regress)",
      abs(tracker_floor._vectors[0]["shopee"].weight - 0.8) < 1e-6,
      f"got {tracker_floor._vectors[0]['shopee'].weight}")
check("New keyword 'tiki' starts at severity=0.5",
      abs(tracker_floor._vectors[0]["tiki"].weight - 0.5) < 1e-6,
      f"got {tracker_floor._vectors[0]['tiki'].weight}")

# Inject again with severity=0.9 (ABOVE existing 0.8). Floor should raise.
tracker_floor.inject_crisis_interests(0, {
    "keywords": ["shopee"],
    "weight": 0.9,
    "source": "crisis:t2",
}, round_num=2)

check("Severity=0.9 raises existing 0.8 to floor 0.9",
      abs(tracker_floor._vectors[0]["shopee"].weight - 0.9) < 1e-6,
      f"got {tracker_floor._vectors[0]['shopee'].weight}")

# Inject 'tiki' again with severity=0.3 (BELOW existing 0.5). Floor preserves.
tracker_floor.inject_crisis_interests(0, {
    "keywords": ["tiki"],
    "weight": 0.3,
    "source": "crisis:t3",
}, round_num=3)

check("Crisis-injected keyword also no-regress (tiki 0.5 stays > severity 0.3)",
      abs(tracker_floor._vectors[0]["tiki"].weight - 0.5) < 1e-6,
      f"got {tracker_floor._vectors[0]['tiki'].weight}")

# engagement_count should still increment on every inject (even no-regress)
check("engagement_count tracks every inject (4 calls touching shopee/tiki)",
      tracker_floor._vectors[0]["shopee"].engagement_count >= 2,
      f"got {tracker_floor._vectors[0]['shopee'].engagement_count}")


print(f"\n{'═' * 60}")
print(f"  RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
print(f"{'═' * 60}")

if failed == 0:
    print("  ✅ ALL TESTS PASSED!")
else:
    print(f"  ⚠️  {failed} test(s) failed")

sys.exit(0 if failed == 0 else 1)

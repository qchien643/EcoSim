"""Test ChromaDB distances and decay effect for current simulation."""
import sys, os
sys.path.insert(0, r"e:\code\project\DUT_STARTUP\EcoSim\oasis")
os.chdir(r"e:\code\project\DUT_STARTUP\EcoSim\oasis")

from interest_feed import PostIndexer, EngagementTracker, build_interest_text
import json

DB = r"e:\code\project\DUT_STARTUP\EcoSim\oasis\data\ecosim_simulation.db"
PROFILES_PATH = r"e:\code\project\DUT_STARTUP\EcoSim\data\profiles"

# Load profiles
PROFILES_PATH = r"e:\code\project\DUT_STARTUP\EcoSim\backend\test_output\test_profiles.json"
with open(PROFILES_PATH, "r", encoding="utf-8") as fh:
    profiles = json.load(fh)

print(f"Loaded {len(profiles)} profiles")

# Init indexer and index posts
indexer = PostIndexer()
indexer.index_from_db(DB)
print(f"Indexed {indexer.count} posts from DB")

# Test with agent_0 interests
agent0 = profiles[0]
interest = build_interest_text(agent0)
print(f"\nAgent 0 interests: {interest[:100]}...")

# Raw query: all posts, raw semantic distances
raw = indexer.query_by_interests(interest, n_results=indexer.count)
print(f"\n=== RAW SEMANTIC DISTANCES (agent 0) ===")
for pid, dist in raw:
    print(f"  post_{pid}: {dist:.4f}")

# Test unified query with NO decay
tracker_empty = EngagementTracker()
unified_no_decay = indexer.query_unified(interest, profiles, tracker_empty, 0, n_results=10)
print(f"\n=== UNIFIED (no decay) ===")
for pid, dist in unified_no_decay:
    print(f"  post_{pid}: {dist:.4f}")

# Test unified query WITH decay (simulate agent_0 commented on post_2 once)
tracker_with = EngagementTracker()
tracker_with.record_comment(0, 2)
unified_with_decay = indexer.query_unified(interest, profiles, tracker_with, 0, n_results=10)
print(f"\n=== UNIFIED (after 1 comment on post_2) ===")
for pid, dist in unified_with_decay:
    print(f"  post_{pid}: {dist:.4f}")

# Test with 2 comments on post_2
tracker_with.record_comment(0, 2)
unified_2x = indexer.query_unified(interest, profiles, tracker_with, 0, n_results=10)
print(f"\n=== UNIFIED (after 2 comments on post_2) ===")
for pid, dist in unified_2x:
    print(f"  post_{pid}: {dist:.4f}")

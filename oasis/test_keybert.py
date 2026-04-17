import sys, os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
sys.path.insert(0, '.')
from agent_cognition import _extract_keyphrases

tests = [
    "Shopee Black Friday Sale Amazing deals on electronics and fashion",
    "Respiratory health significantly boosted by air quality measures in public spaces",
    "Exploring rare earth element chemistry in materials science for sustainable energy",
    "Flash sale Shopee hom nay giam gia cuc soc deal hot nhat",
    "Join us for upcoming K-pop concert in Ho Chi Minh City featuring BTS and Blackpink",
    "The environmental impact of rare earth mining on local communities and ecosystems",
]

for i, t in enumerate(tests):
    result = _extract_keyphrases(t)
    print(f"Test {i+1}: {result}")
    print(f"  Input: {t}")
    print()

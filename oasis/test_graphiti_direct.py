"""Direct Graphiti test — write one episode, then search."""
import asyncio
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ECOSIM_ROOT = os.path.dirname(SCRIPT_DIR)
OUT = os.path.join(SCRIPT_DIR, "data", "graphiti_test.txt")

# Load .env
with open(os.path.join(ECOSIM_ROOT, ".env"), "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
os.environ["OPENAI_API_KEY"] = os.environ.get("LLM_API_KEY", "")


async def test():
    log = []
    try:
        from graphiti_core import Graphiti
        from graphiti_core.driver.falkordb_driver import FalkorDriver
        from graphiti_core.nodes import EpisodeType
        from graphiti_core.search.search_config_recipes import SearchMethod
        from datetime import datetime, timezone

        log.append("Creating FalkorDriver(localhost:6379)...")
        driver = FalkorDriver(host="localhost", port=6379)

        log.append("Creating Graphiti instance...")
        g = Graphiti(graph_driver=driver)

        log.append("Building indices...")
        await g.build_indices_and_constraints()
        log.append("Indices OK")

        log.append("Adding test episode...")
        await g.add_episode(
            name="test_direct_episode",
            episode_body="Agent TestBot posted on Reddit: Shopee Black Friday 2026 is amazing! Great deals on tech products.",
            source=EpisodeType.text,
            reference_time=datetime.now(timezone.utc),
            source_description="direct test",
            group_id="test_direct",
        )
        log.append("Episode added successfully!")

        log.append("Searching for 'Shopee Black Friday'...")
        results = await g.search(query="Shopee Black Friday", num_results=5, search_method=SearchMethod.COMBINED_HYBRID_SEARCH_CROSS_ENCODER)
        log.append("Found {} results".format(len(results)))
        for i, r in enumerate(results):
            log.append("  [{}] {}".format(i, str(r)[:300]))

        log.append("Searching for 'TestBot'...")
        results2 = await g.search(query="TestBot", num_results=5, search_method=SearchMethod.COMBINED_HYBRID_SEARCH_CROSS_ENCODER)
        log.append("Found {} results".format(len(results2)))
        for i, r in enumerate(results2):
            log.append("  [{}] {}".format(i, str(r)[:300]))

        await g.close()
        log.append("DONE - SUCCESS")
    except Exception as e:
        import traceback
        log.append("ERROR: {}".format(e))
        log.append(traceback.format_exc())

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    print("Results saved to:", OUT)

asyncio.run(test())

"""Verify unified graph: campaign docs + simulation traces in same FalkorDB graph."""
import asyncio
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ECOSIM_ROOT = os.path.dirname(SCRIPT_DIR)
OUT = os.path.join(SCRIPT_DIR, "data", "unified_graph_verify.txt")

with open(os.path.join(ECOSIM_ROOT, ".env"), "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
os.environ["OPENAI_API_KEY"] = os.environ.get("LLM_API_KEY", "")

async def main():
    log = []
    from falkordb import FalkorDB as FDB
    graph_name = "shopee_bf_2026"

    fdb = FDB(host="localhost", port=6379)
    g = fdb.select_graph(graph_name)

    # General stats
    r = g.query("MATCH (n) RETURN count(n)")
    nodes = r.result_set[0][0]
    r = g.query("MATCH ()-[r]->() RETURN count(r)")
    edges = r.result_set[0][0]
    log.append("=== Unified Graph: {} ===".format(graph_name))
    log.append("Total Nodes: {} | Total Edges: {}".format(nodes, edges))

    # Count by label
    log.append("\n--- Node Labels ---")
    r = g.query("MATCH (n) RETURN labels(n), count(n) ORDER BY count(n) DESC")
    for row in r.result_set:
        log.append("  {}: {}".format(row[0], row[1]))

    # Count by edge type
    log.append("\n--- Edge Types ---")
    r = g.query("MATCH ()-[r]->() RETURN DISTINCT type(r), count(r) ORDER BY count(r) DESC")
    for row in r.result_set:
        log.append("  {}: {}".format(row[0], row[1]))

    # Campaign-only entities (from document)
    log.append("\n--- Campaign Entities (from document) ---")
    campaign_queries = [
        "MATCH (n:Entity) WHERE n.name CONTAINS 'iPhone' OR n.name CONTAINS 'Samsung' RETURN n.name, n.summary LIMIT 5",
        "MATCH (n:Entity) WHERE n.name CONTAINS 'budget' OR n.name CONTAINS 'VND' OR n.name CONTAINS 'USD' RETURN n.name, n.summary LIMIT 5",
        "MATCH (n:Entity) WHERE n.name CONTAINS 'Gen Z' OR n.name CONTAINS 'consumers' RETURN n.name, n.summary LIMIT 5",
    ]
    for q in campaign_queries:
        try:
            r = g.query(q)
            for row in r.result_set:
                log.append("  {} : {}".format(row[0], (str(row[1]) or "")[:100]))
        except:
            pass

    # Simulation-only entities (from agents)
    log.append("\n--- Simulation Entities (from agents) ---")
    r = g.query("MATCH (n:Entity) WHERE n.name CONTAINS 'Agent' RETURN n.name, n.summary LIMIT 10")
    for row in r.result_set:
        log.append("  {} : {}".format(row[0], (str(row[1]) or "")[:100]))

    # CROSS-QUERY: Campaign concept → Agent behavior
    log.append("\n=== CROSS-QUERIES: Campaign ↔ Simulation ===")

    from graphiti_core import Graphiti
    from graphiti_core.driver.falkordb_driver import FalkorDriver
    driver = FalkorDriver(host="localhost", port=6379, database=graph_name)
    graphiti = Graphiti(graph_driver=driver)

    from graphiti_core.search.search_config_recipes import SearchMethod

    cross_queries = [
        ("eco-friendly products agents", "Campaign eco-friendly → Agent reactions?"),
        ("Shopee Black Friday sale agent comment", "Campaign event → Agent activity?"),
        ("health wellness products interest", "Product category → Agent interest?"),
        ("technology innovation smartphones", "Technology products → Discussion?"),
        ("Gen Z young professionals shopping", "Target audience behavior?"),
    ]

    for q, desc in cross_queries:
        log.append("\n🔍 {} → '{}'".format(desc, q))
        try:
            results = await graphiti.search(query=q, num_results=5, group_ids=[graph_name], search_method=SearchMethod.COMBINED_HYBRID_SEARCH_CROSS_ENCODER)
            log.append("   {} results:".format(len(results)))
            for i, r in enumerate(results):
                log.append("   [{}] {} : {}".format(
                    i, getattr(r, 'name', '?'), str(getattr(r, 'fact', ''))[:140]))
        except Exception as e:
            log.append("   Error: {}".format(e))

    await graphiti.close()
    log.append("\nDONE")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    print("Results:", OUT)

asyncio.run(main())

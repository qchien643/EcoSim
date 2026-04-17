"""Verify FalkorDB graph memory: list available graphs and search."""
import asyncio
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ECOSIM_ROOT = os.path.dirname(SCRIPT_DIR)
OUT = os.path.join(SCRIPT_DIR, "data", "graph_verify_results.txt")

# Load .env
with open(os.path.join(ECOSIM_ROOT, ".env"), "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
os.environ["OPENAI_API_KEY"] = os.environ.get("LLM_API_KEY", "")


async def main():
    log = []
    try:
        from falkordb import FalkorDB as FDB
        from falkor_graph_memory import FalkorGraphSearcher

        # List available simulation graphs
        fdb = FDB(host="localhost", port=6379)
        all_graphs = fdb.list_graphs()
        sim_graphs = [g for g in all_graphs if g.startswith("ecosim_")]
        log.append("Available simulation graphs: {}".format(sim_graphs))

        if not sim_graphs:
            log.append("No simulation data in FalkorDB!")
            with open(OUT, "w", encoding="utf-8") as f:
                f.write("\n".join(log))
            return

        # Use most recent simulation graph
        graph_name = sim_graphs[-1]
        log.append("Using graph: {}".format(graph_name))

        # Count nodes/edges
        g = fdb.select_graph(graph_name)
        result = g.query("MATCH (n) RETURN count(n) as cnt")
        node_count = result.result_set[0][0] if result.result_set else 0
        result = g.query("MATCH ()-[r]->() RETURN count(r) as cnt")
        edge_count = result.result_set[0][0] if result.result_set else 0
        log.append("Nodes: {} | Edges: {}".format(node_count, edge_count))

        # Search using FalkorGraphSearcher
        searcher = FalkorGraphSearcher(database=graph_name)
        await searcher.connect()

        queries = [
            "Shopee Black Friday",
            "Agent posted",
            "health products",
            "eco-friendly",
            "technology innovation",
        ]

        for q in queries:
            log.append("\n=== Search: '{}' ===".format(q))
            results = await searcher.search(query=q, group_id=graph_name)
            log.append("Found {} results:".format(len(results)))
            for i, r in enumerate(results[:5]):
                log.append("  [{}] {} : {}".format(
                    i, getattr(r, 'name', '?'),
                    str(getattr(r, 'fact', ''))[:150]
                ))

        await searcher.close()
        log.append("\nDONE - SUCCESS")
    except Exception as e:
        import traceback
        log.append("ERROR: {}".format(e))
        log.append(traceback.format_exc())

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    print("Results saved to:", OUT)

asyncio.run(main())

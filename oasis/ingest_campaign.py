"""
CLI: Ingest campaign document into FalkorDB knowledge graph.

Usage:
    python ingest_campaign.py --doc campaign_brief.md
    python ingest_campaign.py --doc brief.md --group-id shopee_bf_2026
"""
import asyncio
import argparse
import logging
import os
import sys

# Fix Windows encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ECOSIM_ROOT = os.path.dirname(SCRIPT_DIR)

# Load .env
ENV_PATH = os.path.join(ECOSIM_ROOT, ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

# Set OpenAI key for Graphiti
api_key = os.environ.get("LLM_API_KEY", "")
if api_key:
    os.environ["OPENAI_API_KEY"] = api_key

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


async def main():
    parser = argparse.ArgumentParser(
        description="Ingest campaign document into FalkorDB knowledge graph"
    )
    parser.add_argument(
        "--doc", required=True,
        help="Path to campaign document (MD/TXT/JSON)"
    )
    parser.add_argument(
        "--group-id", default=None,
        help="Graph group ID (shared with simulation). Default: auto from filename."
    )
    parser.add_argument(
        "--falkor-host", default=os.environ.get("FALKORDB_HOST", "localhost"),
        help="FalkorDB host"
    )
    parser.add_argument(
        "--falkor-port", type=int,
        default=int(os.environ.get("FALKORDB_PORT", "6379")),
        help="FalkorDB port"
    )
    args = parser.parse_args()

    # Auto group_id from filename if not specified
    if not args.group_id:
        from pathlib import Path
        stem = Path(args.doc).stem.lower()
        # Clean filename for graph name
        args.group_id = stem.replace(" ", "_").replace("-", "_")

    from campaign_knowledge import CampaignKnowledgePipeline

    pipeline = CampaignKnowledgePipeline(
        api_key=os.environ.get("LLM_API_KEY", ""),
        base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        model=os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini"),
        falkor_host=args.falkor_host,
        falkor_port=args.falkor_port,
        group_id=args.group_id,
    )

    result = await pipeline.run(
        document_path=args.doc,
        source_description=f"Campaign document: {os.path.basename(args.doc)}",
    )

    # Print summary
    print("\n" + "=" * 60)
    print("📊 Ingestion Summary")
    print("=" * 60)
    print(f"  Document:     {args.doc}")
    print(f"  Group ID:     {result['group_id']}")
    print(f"  Sections:     {result['sections_parsed']} parsed → {result['sections_analyzed']} analyzed → {result['episodes_written']} loaded")
    print(f"  Entities:     {result['entities_total']}")
    print(f"  Facts:        {result['facts_total']}")
    print(f"\n💡 To run simulation on the same graph:")
    print(f"   python run_simulation.py --group-id {result['group_id']}")
    print(f"\n🔍 To search the graph:")
    print(f"   python verify_graph.py  (update graph_name in script)")


asyncio.run(main())

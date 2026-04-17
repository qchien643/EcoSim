"""
EcoSim Simulation Service — FastAPI (async)
Handles simulation, knowledge graph, survey, and campaign ingestion.

Run:  .venv/Scripts/python -m uvicorn sim_service:app --port 5002
Port: 5002
Venv: oasis/.venv (camel-ai, graphiti-core[falkordb])
"""
import logging
import os
import sys

# Fix Windows encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Load .env ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ECOSIM_ROOT = os.path.dirname(SCRIPT_DIR)
ENV_PATH = os.path.join(ECOSIM_ROOT, ".env")

if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

# Map LLM key for Graphiti
api_key = os.environ.get("LLM_API_KEY", "")
if api_key:
    os.environ["OPENAI_API_KEY"] = api_key

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sim-svc] %(name)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ── FastAPI App ──
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="EcoSim Simulation Service",
    description="OASIS simulation, knowledge graph, survey, campaign ingestion",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Include Routers ──
from api.simulation import router as sim_router
from api.graph import router as graph_router
from api.survey import router as survey_router
from api.report import router as report_router
from api.interview import router as interview_router

app.include_router(sim_router)
app.include_router(graph_router)
app.include_router(survey_router)
app.include_router(report_router)
app.include_router(interview_router)


@app.get("/api/health")
async def health():
    """Service health check."""
    return {
        "status": "ok",
        "service": "simulation",
        "port": int(os.getenv("SIM_SERVICE_PORT", 5002)),
        "falkordb": f"{os.getenv('FALKORDB_HOST', 'localhost')}:{os.getenv('FALKORDB_PORT', '6379')}",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SIM_SERVICE_PORT", 5002))
    print(f"🤖 EcoSim Simulation Service starting on port {port}")
    print(f"   FalkorDB: {os.getenv('FALKORDB_HOST', 'localhost')}:{os.getenv('FALKORDB_PORT', '6379')}")
    print(f"   Health: http://localhost:{port}/api/health")
    print(f"   Docs:   http://localhost:{port}/docs")
    uvicorn.run("sim_service:app", host="0.0.0.0", port=port, reload=True)

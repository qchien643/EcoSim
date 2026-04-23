"""
EcoSim Simulation Service — FastAPI (async)
Handles simulation, knowledge graph, survey, and campaign ingestion.

Run:  .venv/Scripts/python -m uvicorn sim_service:app --port 5002
Port: 5002
Venv: oasis/.venv (camel-ai, graphiti-core[falkordb])
"""
import logging
import os
import pathlib
import sys

# Fix Windows encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Bootstrap shared library (ecosim_common) ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
def _find_repo_root(start: str) -> str:
    here = pathlib.Path(start).resolve()
    for parent in [here, *here.parents]:
        if (parent / "libs" / "ecosim-common" / "src").is_dir():
            return str(parent)
    return os.path.dirname(start)
ECOSIM_ROOT = _find_repo_root(SCRIPT_DIR)
_SHARED = pathlib.Path(ECOSIM_ROOT) / "libs" / "ecosim-common" / "src"
if _SHARED.is_dir() and str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

# Load .env + remap LLM_API_KEY → OPENAI_API_KEY (via unified config)
from ecosim_common.config import EcoSimConfig
EcoSimConfig.init(pathlib.Path(ECOSIM_ROOT))

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

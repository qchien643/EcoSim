"""
EcoSim Core Service — Entry Point
Run: python run.py (port 5001)
"""

from app import create_app
from app.config import Config
import os

Config.ensure_dirs()
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("CORE_SERVICE_PORT", 5001))
    print(f"🚀 EcoSim Core Service starting on port {port}...")
    print(f"   LLM: {Config.LLM_MODEL_NAME}")
    print(f"   Health: http://localhost:{port}/api/health")
    print(f"   NOTE: Graph/Sim/Survey → Simulation Service (port 5002)")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=Config.DEBUG,
    )

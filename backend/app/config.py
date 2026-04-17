"""
EcoSim Configuration — loads from .env file.
"""

import os
from dotenv import load_dotenv

# Load .env from project root (EcoSim/.env)
_env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(os.path.abspath(_env_path))


class Config:
    """Central configuration loaded from environment variables."""

    # --- Flask ---
    DEBUG = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    PORT = int(os.getenv("FLASK_PORT", 5000))
    MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", 50))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_SIZE_MB * 1024 * 1024

    # --- LLM ---
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")

    # --- FalkorDB ---
    FALKORDB_HOST = os.getenv("FALKORDB_HOST", "localhost")
    FALKORDB_PORT = int(os.getenv("FALKORDB_PORT", 6379))
    FALKORDB_BOLT_PORT = int(os.getenv("FALKORDB_BOLT_PORT", 7687))

    # --- Parquet Profile Dataset ---
    PARQUET_PROFILE_PATH = os.getenv(
        "PARQUET_PROFILE_PATH",
        os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
            "data", "dataGenerator", "profile.parquet",
        )
    )

    # --- Directories ---
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    UPLOAD_DIR = os.path.join(BASE_DIR, os.getenv("UPLOAD_DIR", "uploads"))
    SIM_DIR = os.path.join(DATA_DIR, "simulations")

    @classmethod
    def ensure_dirs(cls):
        """Create data directories if they don't exist."""
        for d in [cls.DATA_DIR, cls.UPLOAD_DIR, cls.SIM_DIR]:
            os.makedirs(d, exist_ok=True)

    def __repr__(self):
        return (
            f"Config(LLM={self.LLM_MODEL_NAME}, "
            f"FalkorDB={self.FALKORDB_HOST}:{self.FALKORDB_PORT})"
        )

"""
EcoSim unified configuration.

Centralize 3 cách load `.env` hiện có:
  - backend/app/config.py dùng python-dotenv
  - oasis/sim_service.py tự parse .env bằng tay + remap LLM_API_KEY → OPENAI_API_KEY
  - gateway/gateway.py tự parse .env bằng tay lần nữa

Thay bằng 1 `EcoSimConfig` load 1 lần, auto-locate .env từ bất kỳ cwd nào,
và remap key LLM → OPENAI tự động cho Graphiti.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _locate_repo_root(start: Optional[Path] = None) -> Path:
    """Đi ngược lên tìm folder chứa `.env` hoặc `docker-compose.yml`.

    Gọi được từ bất kỳ cwd nào trong repo — backend/, oasis/, gateway/, shared/.
    Fallback: cwd nếu không tìm thấy marker (development mode).
    """
    if start is None:
        start = Path(__file__).resolve()
    cur = start if start.is_dir() else start.parent
    for parent in [cur, *cur.parents]:
        if (parent / ".env").exists() or (parent / "docker-compose.yml").exists():
            return parent
    return Path.cwd()


def _load_env_file(path: Path) -> None:
    """Parse `.env` và set `os.environ` nếu chưa có (setdefault).

    Dùng python-dotenv nếu có (handles quotes, escapes, multiline); nếu không
    thì fallback parse đơn giản `KEY=VALUE`.
    """
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
        return
    except ImportError:
        pass
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


class EcoSimConfig:
    """Single source of truth cho config.

    Khởi tạo (chỉ 1 lần per process) tự động:
      1. Locate repo root
      2. Load .env file
      3. Remap LLM_API_KEY → OPENAI_API_KEY cho Graphiti/sentence-transformers
    """

    _initialized: bool = False
    _repo_root: Optional[Path] = None

    @classmethod
    def init(cls, repo_root: Optional[Path] = None) -> None:
        """Idempotent init. Gọi 1 lần ở entry point của mỗi service."""
        if cls._initialized:
            return
        cls._repo_root = (repo_root or _locate_repo_root()).resolve()
        _load_env_file(cls._repo_root / ".env")
        # Remap LLM key cho libraries đọc OPENAI_API_KEY trực tiếp
        api_key = os.environ.get("LLM_API_KEY", "")
        if api_key and not os.environ.get("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = api_key
        cls._initialized = True

    # ── Repo layout ──
    @classmethod
    def repo_root(cls) -> Path:
        cls.init()
        assert cls._repo_root is not None
        return cls._repo_root

    @classmethod
    def data_dir(cls) -> Path:
        return cls.repo_root() / "data"

    @classmethod
    def upload_dir(cls) -> Path:
        cls.init()
        # Ưu tiên UPLOAD_DIR env; mặc định là data/uploads
        custom = os.environ.get("UPLOAD_DIR")
        if custom:
            p = Path(custom)
            return p if p.is_absolute() else cls.repo_root() / custom
        return cls.data_dir() / "uploads"

    @classmethod
    def sim_dir(cls) -> Path:
        return cls.data_dir() / "simulations"

    @classmethod
    def parquet_profile_path(cls) -> Path:
        cls.init()
        custom = os.environ.get("PARQUET_PROFILE_PATH")
        if custom:
            p = Path(custom)
            return p if p.is_absolute() else cls.repo_root() / custom
        return cls.data_dir() / "dataGenerator" / "profile.parquet"

    @classmethod
    def ensure_dirs(cls) -> None:
        for d in [cls.data_dir(), cls.upload_dir(), cls.sim_dir()]:
            d.mkdir(parents=True, exist_ok=True)

    # ── LLM ──
    @classmethod
    def llm_api_key(cls) -> str:
        cls.init()
        return os.environ.get("LLM_API_KEY", "")

    @classmethod
    def llm_base_url(cls) -> str:
        cls.init()
        return os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")

    @classmethod
    def llm_model_name(cls) -> str:
        cls.init()
        return os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")

    # ── FalkorDB ──
    @classmethod
    def falkordb_host(cls) -> str:
        cls.init()
        return os.environ.get("FALKORDB_HOST", "localhost")

    @classmethod
    def falkordb_port(cls) -> int:
        cls.init()
        return int(os.environ.get("FALKORDB_PORT", 6379))

    @classmethod
    def falkordb_bolt_port(cls) -> int:
        cls.init()
        return int(os.environ.get("FALKORDB_BOLT_PORT", 7687))

    @classmethod
    def falkordb_database(cls) -> str:
        cls.init()
        return os.environ.get("FALKORDB_DATABASE", "ecosim")

    # ── Flask / ports ──
    @classmethod
    def core_port(cls) -> int:
        cls.init()
        return int(os.environ.get("CORE_SERVICE_PORT", os.environ.get("FLASK_PORT", 5001)))

    @classmethod
    def sim_port(cls) -> int:
        cls.init()
        return int(os.environ.get("SIM_SERVICE_PORT", 5002))

    @classmethod
    def gateway_port(cls) -> int:
        cls.init()
        return int(os.environ.get("GATEWAY_PORT", 5000))

    @classmethod
    def debug(cls) -> bool:
        cls.init()
        return os.environ.get("FLASK_DEBUG", "true").lower() == "true"

    @classmethod
    def max_upload_mb(cls) -> int:
        cls.init()
        return int(os.environ.get("MAX_UPLOAD_SIZE_MB", 50))

    def __repr__(self) -> str:
        return (
            f"EcoSimConfig(LLM={self.llm_model_name()}, "
            f"FalkorDB={self.falkordb_host()}:{self.falkordb_port()})"
        )

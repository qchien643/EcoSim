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
    def campaigns_dir(cls) -> Path:
        """Per-campaign data root. Was `data/uploads/`, đổi sang `data/campaigns/`
        ở Phase 5 (folder reorg). Override qua env `CAMPAIGNS_DIR` hoặc legacy
        `UPLOAD_DIR` (backward compat).
        """
        cls.init()
        custom = os.environ.get("CAMPAIGNS_DIR") or os.environ.get("UPLOAD_DIR")
        if custom:
            p = Path(custom)
            return p if p.is_absolute() else cls.repo_root() / custom
        return cls.data_dir() / "campaigns"

    # Legacy alias — keep cho code chưa migrate. Internal dùng campaigns_dir().
    @classmethod
    def upload_dir(cls) -> Path:
        return cls.campaigns_dir()

    # ── Legacy alias — sim folder bây giờ nested dưới campaign ──
    # Phase 10: data/simulations/ KHÔNG còn dùng. Sim folder = data/campaigns/<cid>/sims/<sid>/.
    # Giữ helper này tạm cho code chưa migrate (deprecated, sẽ remove ở Phase 11).
    @classmethod
    def sim_dir(cls) -> Path:
        """DEPRECATED — sim folders giờ nested dưới campaigns/<cid>/sims/.
        Dùng path_resolver.compute_simulation_paths(sid, cid) để lấy sim_dir đúng.
        """
        return cls.data_dir() / "simulations"

    # ── Phase 10: SQLite metadata index — ground truth cho routing ──
    @classmethod
    def meta_db_path(cls) -> Path:
        cls.init()
        custom = os.environ.get("META_DB_PATH")
        if custom:
            p = Path(custom)
            return p if p.is_absolute() else cls.repo_root() / custom
        return cls.data_dir() / "meta.db"

    # ── Phase 10: campaign + sim folder helpers (convention-based) ──
    # Khuyến nghị: dùng path_resolver.compute_*_paths() / resolve_*_paths()
    # thay vì helpers này — đã có DB-backed routing đầy đủ.
    @classmethod
    def campaign_dir(cls, campaign_id: str) -> Path:
        if not campaign_id:
            raise ValueError("campaign_id required")
        return cls.campaigns_dir() / campaign_id

    @classmethod
    def campaign_source_dir(cls, campaign_id: str) -> Path:
        return cls.campaign_dir(campaign_id) / "source"

    @classmethod
    def campaign_extracted_dir(cls, campaign_id: str) -> Path:
        return cls.campaign_dir(campaign_id) / "extracted"

    @classmethod
    def campaign_kg_dir(cls, campaign_id: str) -> Path:
        return cls.campaign_dir(campaign_id) / "kg"

    @classmethod
    def campaign_sims_dir(cls, campaign_id: str) -> Path:
        """Parent dir chứa N sims của 1 campaign."""
        return cls.campaign_dir(campaign_id) / "sims"

    @classmethod
    def sim_kg_dir(cls, sim_id: str, campaign_id: Optional[str] = None) -> Path:
        """Phase 10: nested layout. Cần campaign_id để build path đúng.

        Backward-compat: nếu campaign_id không truyền, query meta.db lookup cid.
        Tránh dùng pattern này — dùng path_resolver.compute_simulation_paths().
        """
        if not sim_id:
            raise ValueError("sim_id required")
        if campaign_id:
            return cls.campaign_dir(campaign_id) / "sims" / sim_id / "kg"
        # Lookup cid từ meta.db
        try:
            from .metadata_index import get_simulation
            sim = get_simulation(sim_id)
            if sim and sim.get("cid"):
                return cls.campaign_dir(sim["cid"]) / "sims" / sim_id / "kg"
        except Exception:
            pass
        # Last resort: legacy flat path (warning)
        return cls.data_dir() / "simulations" / sim_id / "kg"

    @classmethod
    def reference_dir(cls) -> Path:
        """Reference data (parquet pool, name lists, MBTI distribution)."""
        return cls.data_dir() / "reference"

    @classmethod
    def parquet_profile_path(cls) -> Path:
        """Profile parquet location. Was `data/dataGenerator/`, đổi sang
        `data/reference/` ở Phase 5 (clearer purpose).
        Backward compat: nếu data/dataGenerator/profile.parquet vẫn tồn tại
        (chưa migrate), dùng nó. Override qua env PARQUET_PROFILE_PATH.
        """
        cls.init()
        custom = os.environ.get("PARQUET_PROFILE_PATH")
        if custom:
            p = Path(custom)
            return p if p.is_absolute() else cls.repo_root() / custom
        new_path = cls.data_dir() / "reference" / "profile.parquet"
        if new_path.exists():
            return new_path
        legacy = cls.data_dir() / "dataGenerator" / "profile.parquet"
        if legacy.exists():
            return legacy
        return new_path  # default to new path even if missing (caller raise)

    @classmethod
    def ensure_dirs(cls) -> None:
        for d in [cls.data_dir(), cls.campaigns_dir(), cls.reference_dir()]:
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

    @classmethod
    def llm_fast_model_name(cls) -> str:
        """Cheaper/faster model cho các call không cần chất lượng cao (default =
        main model). Dùng cho: intent classification, in-character agent reply,
        light aggregation calls — nơi prompt đã có context đầy đủ.

        Override qua env `LLM_FAST_MODEL_NAME` để chỉ định model rẻ hơn,
        ví dụ `gpt-3.5-turbo`, `gpt-4o-mini`, Groq Llama, local Ollama...
        """
        cls.init()
        fast = os.environ.get("LLM_FAST_MODEL_NAME", "").strip()
        return fast or cls.llm_model_name()

    @classmethod
    def llm_extraction_model_name(cls) -> str:
        """Stronger model cho stages chiết xuất tài liệu (campaign spec
        extraction Stage 1 + section entity/fact analysis Stage 3 trong
        Knowledge Graph build pipeline).

        Default `gpt-4o` — đắt hơn ~5× `gpt-4o-mini` nhưng precision cao hơn
        khi extract entities/facts từ Vietnamese business docs (ít nhầm
        "Brand"→"Company", catch implicit relationships tốt hơn).

        Cost mitigated bởi cache: extracted/sections.json + analyzed.json
        được persist sau lần build đầu, build sau reuse cache (skip LLM).

        Override env `LLM_EXTRACTION_MODEL`. Set rỗng → fallback về
        `LLM_MODEL_NAME` để giảm cost ở dev (entities sẽ noise hơn).
        """
        cls.init()
        extr = os.environ.get("LLM_EXTRACTION_MODEL", "").strip()
        return extr or "gpt-4o"

    # ── Embedding ──
    # Centralize embedder qua provider của LLM (OpenAI-compatible). Tránh trộn
    # local sentence-transformers (384-dim) với OpenAI (1536-dim) gây 2 vector
    # spaces incompatible. Default = text-embedding-3-small (rẻ, đủ tốt).
    # Optional override base_url + api_key để fallback sang OpenAI khi
    # primary provider không có embeddings (vd Groq chỉ có chat).

    # Bảng dim cho các model OpenAI thông dụng — dùng để probe nhanh không cần
    # API call. Nếu model không có ở đây, LLMClient.embedding_dim sẽ probe
    # bằng 1 call thật.
    _EMBEDDING_DIMS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    @classmethod
    def llm_embedding_model(cls) -> str:
        cls.init()
        return os.environ.get("LLM_EMBEDDING_MODEL", "text-embedding-3-small").strip()

    @classmethod
    def llm_embedding_base_url(cls) -> str:
        """Override cho embedding endpoint. Default = chat base_url."""
        cls.init()
        override = os.environ.get("LLM_EMBEDDING_BASE_URL", "").strip()
        return override or cls.llm_base_url()

    @classmethod
    def llm_embedding_api_key(cls) -> str:
        """Override cho embedding api key. Default = chat api_key."""
        cls.init()
        override = os.environ.get("LLM_EMBEDDING_API_KEY", "").strip()
        return override or cls.llm_api_key()

    @classmethod
    def llm_embedding_dim_hint(cls, model: Optional[str] = None) -> Optional[int]:
        """Lookup dim cho model đã biết. Trả None nếu không biết → caller probe."""
        cls.init()
        m = model or cls.llm_embedding_model()
        return cls._EMBEDDING_DIMS.get(m)

    # ── Zep Cloud (managed KG extraction) ──
    @classmethod
    def zep_api_key(cls) -> str:
        """Zep Cloud API key. Empty nếu chưa config — caller phải fallback
        sang KG_BUILDER=direct hoặc raise rõ ràng.
        """
        cls.init()
        return os.environ.get("ZEP_API_KEY", "").strip()

    @classmethod
    def kg_builder(cls) -> str:
        """KG build engine selection: zep_hybrid | direct | graphiti.

        - `zep_hybrid`: Zep server-side LLM extract → FalkorDB mirror (rich, ~30-60s)
        - `direct`: Stage 2 EcoSim extract → direct Cypher write (fast 12s, info-lossy)
        - `graphiti`: Legacy add_episode (slow, debug only)

        Default `direct` để safe dev (Zep cần API key + costs credit).
        """
        cls.init()
        v = os.environ.get("KG_BUILDER", "direct").strip().lower()
        if v not in ("zep_hybrid", "direct", "graphiti"):
            return "direct"
        return v

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

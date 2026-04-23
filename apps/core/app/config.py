"""
Config — adapter bắc cầu sang ecosim_common.config.EcoSimConfig.

Giữ class `Config` với interface giống trước để code cũ không phải đổi.
Nguồn thật của config là `shared/src/ecosim_common/config.py`.
"""

from ecosim_common.config import EcoSimConfig

# Đảm bảo .env được load (idempotent)
EcoSimConfig.init()


class Config:
    """Backward-compat facade cho EcoSimConfig.

    Các call site hiện tại (Config.LLM_API_KEY, Config.FALKORDB_HOST, ...)
    tiếp tục hoạt động. Không thêm field mới ở đây — thêm vào `EcoSimConfig`.
    """

    # --- Flask ---
    DEBUG = EcoSimConfig.debug()
    PORT = EcoSimConfig.core_port()
    MAX_UPLOAD_SIZE_MB = EcoSimConfig.max_upload_mb()
    MAX_CONTENT_LENGTH = MAX_UPLOAD_SIZE_MB * 1024 * 1024

    # --- LLM ---
    LLM_API_KEY = EcoSimConfig.llm_api_key()
    LLM_BASE_URL = EcoSimConfig.llm_base_url()
    LLM_MODEL_NAME = EcoSimConfig.llm_model_name()

    # --- FalkorDB ---
    FALKORDB_HOST = EcoSimConfig.falkordb_host()
    FALKORDB_PORT = EcoSimConfig.falkordb_port()
    FALKORDB_BOLT_PORT = EcoSimConfig.falkordb_bolt_port()

    # --- Directories ---
    BASE_DIR = str(EcoSimConfig.repo_root())
    DATA_DIR = str(EcoSimConfig.data_dir())
    UPLOAD_DIR = str(EcoSimConfig.upload_dir())
    SIM_DIR = str(EcoSimConfig.sim_dir())
    PARQUET_PROFILE_PATH = str(EcoSimConfig.parquet_profile_path())

    @classmethod
    def ensure_dirs(cls):
        EcoSimConfig.ensure_dirs()

    def __repr__(self):
        return repr(EcoSimConfig())

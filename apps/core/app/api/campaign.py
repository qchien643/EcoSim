"""
Campaign API — Upload & parse campaign documents.

Per-campaign storage layout (xem CLAUDE.md §4):

    <UPLOAD_DIR>/<campaign_id>/
      ├── source/<original_filename>       ← tài liệu gốc (immutable)
      ├── extracted/spec.json              ← Stage 1: CampaignSpec
      ├── extracted/sections.json          ← Stage 2: parsed sections (build pipeline)
      ├── extracted/analyzed.json          ← Stage 3: LLM-extracted entities/facts
      ├── kg/build_meta.json               ← KG build metadata
      └── sims.json                        ← manifest list sims thuộc campaign

E2E Flow: U→API→CP→LLM→CampaignSpec → save extracted/spec.json
"""

import json
import logging
import shutil
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

from ecosim_common.atomic_io import atomic_write_json
from ecosim_common.config import EcoSimConfig

from ..config import Config
from ..services.campaign_parser import CampaignParser

logger = logging.getLogger("ecosim.api.campaign")

campaign_bp = Blueprint("campaign", __name__, url_prefix="/api/campaign")

# In-memory storage for parsed campaigns (per session)
_campaigns: dict = {}


def _spec_path(campaign_id: str) -> Path:
    """Phase 8: resolve qua DB trước, fallback convention.

    DB-backed lookup → debug nhanh hơn (SELECT 1 row thấy hết paths).
    Lazy upsert tự động populate DB nếu row mới.
    """
    try:
        from ecosim_common.path_resolver import resolve_campaign_paths
        paths = resolve_campaign_paths(campaign_id)
        if paths.get("spec_path"):
            return Path(paths["spec_path"])
    except Exception as _e:
        logger.debug("resolve_campaign_paths fallback: %s", _e)
    return EcoSimConfig.campaign_extracted_dir(campaign_id) / "spec.json"


@campaign_bp.route("/upload", methods=["POST"])
def upload_campaign():
    """Upload a campaign file (PDF/MD/TXT) and parse it.

    Storage:
      1. Sinh `campaign_id` (8-hex UUID) backend-side TRƯỚC parse (tránh race
         khi LLM trả id khác).
      2. Save file gốc → `<UPLOAD_DIR>/<campaign_id>/source/<original_filename>`.
      3. LLM parse → CampaignSpec (override id = campaign_id sinh trước).
      4. Save spec → `<UPLOAD_DIR>/<campaign_id>/extracted/spec.json`.

    Request: multipart/form-data with 'file' field
    Response: { campaign_id, spec: {...} }
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided. Use form field 'file'."}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in {".pdf", ".md", ".txt", ".markdown"}:
        return jsonify({
            "error": f"Unsupported file type: {ext}",
            "supported": [".pdf", ".md", ".txt"],
        }), 400

    # Phase 12 #5: file size limit (DOS guard). Default 50MB, override .env MAX_UPLOAD_SIZE_MB.
    max_mb = EcoSimConfig.max_upload_mb()
    max_bytes = max_mb * 1024 * 1024
    cl = request.content_length or 0
    if cl > max_bytes:
        return jsonify({
            "error": f"File too large: {cl / 1024 / 1024:.1f}MB exceeds {max_mb}MB limit",
            "max_size_mb": max_mb,
        }), 413  # 413 Payload Too Large

    # Step 1: campaign_id backend-side (Phase 12 #5: 32 hex = 128-bit entropy,
    # collision risk negligible vs 8 hex 32-bit ~birthday paradox at 65k uploads).
    campaign_id = uuid.uuid4().hex

    # Step 2: insert campaign row vào meta.db trước (auto populate paths qua resolver)
    # Sau đó query DB lấy paths thay vì compute inline → single source of truth.
    Config.ensure_dirs()
    from ecosim_common.metadata_index import upsert_campaign
    from ecosim_common.path_resolver import resolve_campaign_paths
    upsert_campaign(campaign_id, status="created")
    paths = resolve_campaign_paths(campaign_id)
    source_dir = Path(paths["source_dir"])
    extracted_dir = Path(paths["extracted_dir"])
    source_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    save_path = source_dir / file.filename
    file.save(str(save_path))
    logger.info(f"File saved: {save_path}")

    # Step 3: parse via LLM extraction model
    try:
        parser = CampaignParser()
        spec = parser.parse_file(str(save_path))

        # Override id sinh từ LLM bằng id deterministic
        spec.campaign_id = campaign_id

        # Cache trong memory
        _campaigns[campaign_id] = spec

        # Step 4: save spec → extracted/spec.json
        atomic_write_json(_spec_path(campaign_id), spec.model_dump(mode="json"))

        # Phase 6.2.1: sync metadata index (best-effort)
        try:
            from ecosim_common.metadata_index import upsert_campaign
            upsert_campaign(
                campaign_id,
                name=spec.name,
                campaign_type=getattr(spec.campaign_type, "value", str(spec.campaign_type)),
                market=spec.market or "",
                source_filename=file.filename,
                source_size_bytes=save_path.stat().st_size,
                created_at=spec.created_at.isoformat() if hasattr(spec.created_at, "isoformat") else str(spec.created_at),
                status="created",
            )
        except Exception as _me:
            logger.warning("Metadata sync (campaign upload) fail: %s", _me)

        return jsonify({
            "campaign_id": campaign_id,
            "spec": spec.model_dump(
                mode="json",
                exclude={"raw_text", "chunks"},
            ),
            "chunks_count": len(spec.chunks),
            "raw_text_length": len(spec.raw_text),
        }), 201

    except Exception as e:
        logger.error(f"Campaign parsing failed: {e}", exc_info=True)
        # Cleanup partial folder nếu parse fail — DB-backed path resolution
        try:
            from ecosim_common.path_resolver import resolve_campaign_paths
            cdir = resolve_campaign_paths(campaign_id).get("campaign_dir")
            if cdir:
                shutil.rmtree(cdir, ignore_errors=True)
            from ecosim_common.metadata_index import delete_campaign
            delete_campaign(campaign_id)
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@campaign_bp.route("/parse", methods=["POST"])
def parse_text():
    """Parse campaign from raw text (JSON body) — KHÔNG persist (debug only).

    Request: { "text": "Campaign description..." }
    Response: { campaign_id, spec: {...} }

    Endpoint này không tạo per-campaign folder vì không có file source. Chỉ
    để debug parser logic. KG build cần upload thực sự để có spec persist.
    """
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Provide 'text' in JSON body"}), 400

    try:
        parser = CampaignParser()
        spec = parser.parse_text(data["text"])

        _campaigns[spec.campaign_id] = spec

        return jsonify({
            "campaign_id": spec.campaign_id,
            "spec": spec.model_dump(
                mode="json",
                exclude={"raw_text", "chunks"},
            ),
            "chunks_count": len(spec.chunks),
        }), 201

    except Exception as e:
        logger.error(f"Text parsing failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@campaign_bp.route("/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id: str):
    """Get a parsed campaign by ID.

    Query params:
        include_text=true  — include raw_text
        include_chunks=true — include chunks
    """
    spec = _campaigns.get(campaign_id)

    if spec is None:
        # Try loading from disk: <id>/extracted/spec.json
        spec_path = _spec_path(campaign_id)
        if spec_path.exists():
            from ..models.campaign import CampaignSpec
            with open(spec_path, "r", encoding="utf-8") as f:
                spec = CampaignSpec(**json.load(f))
            _campaigns[campaign_id] = spec
        else:
            return jsonify({"error": f"Campaign {campaign_id} not found"}), 404

    exclude_fields = set()
    if request.args.get("include_text") != "true":
        exclude_fields.add("raw_text")
    if request.args.get("include_chunks") != "true":
        exclude_fields.add("chunks")

    return jsonify({
        "campaign_id": spec.campaign_id,
        "spec": spec.model_dump(mode="json", exclude=exclude_fields),
    })


@campaign_bp.route("/list", methods=["GET"])
def list_campaigns():
    """List all campaigns. Phase 5: query SQLite metadata index.

    Filesystem fallback nếu DB không sẵn sàng (boot hoặc bootstrap fail).
    """
    campaigns = {}

    # Phase 5: ưu tiên DB query (nhanh, không walk filesystem)
    try:
        from ecosim_common.metadata_index import list_campaigns as db_list
        for r in db_list():
            cid = r["cid"]
            campaigns[cid] = {
                "campaign_id": cid,
                "name": r.get("name") or "Unknown",
                "campaign_type": r.get("campaign_type") or "other",
                "market": r.get("market") or "",
                "created_at": r.get("created_at") or "",
            }
    except Exception as _e:
        logger.warning("DB list fallback to filesystem: %s", _e)
        # Filesystem fallback — glob spec.json
        Config.ensure_dirs()
        upload_dir = EcoSimConfig.campaigns_dir()
        if upload_dir.is_dir():
            for spec_file in upload_dir.glob("*/extracted/spec.json"):
                try:
                    with open(spec_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    cid = data.get("campaign_id", "") or spec_file.parent.parent.name
                    if cid and cid not in campaigns:
                        campaigns[cid] = {
                            "campaign_id": cid,
                            "name": data.get("name", "Unknown"),
                            "campaign_type": data.get("campaign_type", "other"),
                            "market": data.get("market", ""),
                            "created_at": data.get("created_at", ""),
                        }
                except (json.JSONDecodeError, KeyError):
                    pass

    # Merge in-memory cache (may have newer unsynced data)
    for cid, spec in _campaigns.items():
        if cid not in campaigns:
            campaigns[cid] = {
                "campaign_id": cid,
                "name": spec.name,
                "campaign_type": spec.campaign_type.value,
                "market": spec.market,
                "created_at": spec.created_at.isoformat(),
            }

    result = list(campaigns.values())
    return jsonify({"campaigns": result, "count": len(result)})

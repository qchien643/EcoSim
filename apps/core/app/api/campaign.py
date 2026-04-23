"""
Campaign API — Upload & parse campaign documents.

E2E Flow: U→API→CP→LLM→CampaignSpec
"""

import json
import logging
import os

from flask import Blueprint, jsonify, request

from ecosim_common.atomic_io import atomic_write_json

from ..config import Config
from ..services.campaign_parser import CampaignParser

logger = logging.getLogger("ecosim.api.campaign")

campaign_bp = Blueprint("campaign", __name__, url_prefix="/api/campaign")

# In-memory storage for parsed campaigns (per session)
_campaigns: dict = {}


@campaign_bp.route("/upload", methods=["POST"])
def upload_campaign():
    """Upload a campaign file (PDF/MD/TXT) and parse it.

    Request: multipart/form-data with 'file' field
    Response: { campaign_id, spec: {...} }
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided. Use form field 'file'."}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    # Save to uploads dir
    Config.ensure_dirs()
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {".pdf", ".md", ".txt", ".markdown"}:
        return jsonify({
            "error": f"Unsupported file type: {ext}",
            "supported": [".pdf", ".md", ".txt"],
        }), 400

    save_path = os.path.join(Config.UPLOAD_DIR, file.filename)
    file.save(save_path)
    logger.info(f"File saved: {save_path}")

    # Parse campaign
    try:
        parser = CampaignParser()
        spec = parser.parse_file(save_path)

        # Store in memory
        _campaigns[spec.campaign_id] = spec

        # Also save spec as JSON for persistence (atomic write)
        spec_path = os.path.join(
            Config.UPLOAD_DIR, f"{spec.campaign_id}_spec.json"
        )
        atomic_write_json(spec_path, spec.model_dump(mode="json"))

        return jsonify({
            "campaign_id": spec.campaign_id,
            "spec": spec.model_dump(
                mode="json",
                exclude={"raw_text", "chunks"},
            ),
            "chunks_count": len(spec.chunks),
            "raw_text_length": len(spec.raw_text),
        }), 201

    except Exception as e:
        logger.error(f"Campaign parsing failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@campaign_bp.route("/parse", methods=["POST"])
def parse_text():
    """Parse campaign from raw text (JSON body).

    Request: { "text": "Campaign description..." }
    Response: { campaign_id, spec: {...} }
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
        # Try loading from disk
        spec_path = os.path.join(
            Config.UPLOAD_DIR, f"{campaign_id}_spec.json"
        )
        if os.path.exists(spec_path):
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
    """List all parsed campaigns (scans disk + in-memory cache)."""
    campaigns = {}

    # 1. Scan uploads/ for persisted *_spec.json files
    Config.ensure_dirs()
    if os.path.isdir(Config.UPLOAD_DIR):
        import glob
        for spec_file in glob.glob(os.path.join(Config.UPLOAD_DIR, "*_spec.json")):
            try:
                with open(spec_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cid = data.get("campaign_id", "")
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

    # 2. Merge in-memory cache (may have newer data)
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

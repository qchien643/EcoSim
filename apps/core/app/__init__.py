"""
EcoSim Core Service — Campaign + Report API
Flask application factory.
Port: 5001
"""

import os
import logging
from flask import Flask

from .config import Config


def create_app(config_class=Config):
    """Flask application factory pattern."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    # NOTE: CORS đã được Caddy gateway xử lý ở apps/gateway/Caddyfile.
    # Bật CORS(app) ở đây sẽ tạo duplicate `Access-Control-Allow-Origin`
    # header (Caddy add một, Flask-CORS add một) → browser reject với
    # "header contains multiple values, but only one is allowed" → frontend
    # báo "Network error" mặc dù backend trả 200. Browser nói chuyện với
    # backend chỉ qua gateway :5000, không bao giờ trực tiếp.

    # --- Logging ---
    logging.basicConfig(
        level=logging.DEBUG if app.config["DEBUG"] else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("ecosim")
    log.info("EcoSim starting up...")

    # Phase 5: bootstrap metadata index từ filesystem (idempotent).
    # Best-effort — service vẫn start nếu DB init fail (filesystem là source of truth).
    try:
        from ecosim_common.metadata_index import bootstrap_from_filesystem
        stats = bootstrap_from_filesystem()
        log.info("Metadata index bootstrap: %s", stats)
    except Exception as e:
        log.warning("Metadata bootstrap failed (best-effort): %s", e)

    # --- Register Blueprints ---
    # Phase 1: Campaign Input
    from .api.campaign import campaign_bp
    app.register_blueprint(campaign_bp)

    # Report Generation
    from .api.report import report_bp
    app.register_blueprint(report_bp)

    # Phase 7.5: Dashboard cross-cutting analytics
    from .api.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)

    # NOTE: graph, simulation, survey blueprints moved to Simulation Service (port 5002)

    # --- Health check endpoint ---
    @app.route("/api/health")
    def health():
        return {"status": "ok", "service": "ecosim"}

    return app

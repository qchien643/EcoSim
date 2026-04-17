"""
EcoSim Core Service — Campaign + Report API
Flask application factory.
Port: 5001
"""

import os
import logging
from flask import Flask
from flask_cors import CORS

from .config import Config


def create_app(config_class=Config):
    """Flask application factory pattern."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    CORS(app)

    # --- Logging ---
    logging.basicConfig(
        level=logging.DEBUG if app.config["DEBUG"] else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("ecosim")
    log.info("EcoSim starting up...")

    # --- Register Blueprints ---
    # Phase 1: Campaign Input
    from .api.campaign import campaign_bp
    app.register_blueprint(campaign_bp)

    # Report Generation
    from .api.report import report_bp
    app.register_blueprint(report_bp)

    # NOTE: graph, simulation, survey blueprints moved to Simulation Service (port 5002)

    # --- Health check endpoint ---
    @app.route("/api/health")
    def health():
        return {"status": "ok", "service": "ecosim"}

    return app

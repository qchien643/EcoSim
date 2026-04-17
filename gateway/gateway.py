"""
EcoSim API Gateway — Reverse proxy for microservice routing.

Routes:
  /api/campaign/*  → Core Service     (localhost:5001)
  /api/report/*    → Core Service     (localhost:5001)
  /api/sim/*       → Simulation Svc   (localhost:5002)
  /api/graph/*     → Simulation Svc   (localhost:5002)
  /api/survey/*    → Simulation Svc   (localhost:5002)

Run:  python gateway.py
Port: 5000
"""

import logging
import os
import sys
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

# Load .env
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
if os.path.exists(ENV_PATH):
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

app = Flask(__name__)
CORS(app)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [gateway] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gateway")

# ── Service Registry ──
CORE_SERVICE = os.getenv("CORE_SERVICE_URL", "http://localhost:5001")
SIM_SERVICE = os.getenv("SIM_SERVICE_URL", "http://localhost:5002")

ROUTE_MAP = {
    "/api/campaign": CORE_SERVICE,
    "/api/report": CORE_SERVICE,
    "/api/sim": SIM_SERVICE,
    "/api/graph": SIM_SERVICE,
    "/api/survey": SIM_SERVICE,
    "/api/analysis": SIM_SERVICE,
    "/api/interview": SIM_SERVICE,
}

# ── Proxy Logic ──

try:
    import httpx
    _client = httpx.Client(timeout=300.0)  # Long timeout for LLM calls
except ImportError:
    import urllib.request
    _client = None


def _proxy_request(target_url: str):
    """Forward the current Flask request to a target service."""
    url = f"{target_url}{request.full_path}"
    headers = {
        k: v for k, v in request.headers
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }

    if _client:
        # httpx-based proxy (preferred)
        try:
            resp = _client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=request.get_data(),
                params=request.args if not request.query_string else None,
            )
            excluded_headers = {"content-encoding", "transfer-encoding", "content-length"}
            response_headers = [
                (k, v) for k, v in resp.headers.items()
                if k.lower() not in excluded_headers
            ]
            return Response(resp.content, resp.status_code, response_headers)
        except httpx.ConnectError:
            return jsonify({"error": f"Service unavailable: {target_url}"}), 503
        except Exception as e:
            logger.error(f"Proxy error: {e}")
            return jsonify({"error": str(e)}), 502
    else:
        # Fallback: urllib (no httpx)
        try:
            req = urllib.request.Request(url, data=request.get_data(), headers=headers, method=request.method)
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = resp.read()
                return Response(body, resp.status, dict(resp.getheaders()))
        except urllib.error.URLError as e:
            return jsonify({"error": f"Service unavailable: {target_url}"}), 503


def _resolve_service(path: str) -> str | None:
    """Find which service handles this path."""
    for prefix, service_url in ROUTE_MAP.items():
        if path.startswith(prefix):
            return service_url
    return None


def _proxy_request_sse(target_url: str):
    """Forward an SSE request with streaming response."""
    url = f"{target_url}{request.full_path}"
    headers = {
        k: v for k, v in request.headers
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }

    if not _client:
        return jsonify({"error": "httpx required for SSE streaming"}), 500

    try:
        import httpx as _httpx

        def generate():
            try:
                with _httpx.Client(timeout=600.0) as sse_client:
                    with sse_client.stream("GET", url, headers=headers) as resp:
                        for chunk in resp.iter_text():
                            yield chunk
            except GeneratorExit:
                pass
            except Exception as e:
                logger.error(f"SSE stream error: {e}")

        return Response(
            generate(),
            status=200,
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.error(f"SSE proxy error: {e}")
        return jsonify({"error": str(e)}), 502


# ── Route: Catch-all proxy ──

@app.route("/api/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy(path):
    """Route API requests to the correct microservice."""
    full_path = f"/api/{path}"
    service_url = _resolve_service(full_path)

    if not service_url:
        return jsonify({"error": f"No service registered for: {full_path}"}), 404

    logger.info(f"→ {request.method} {full_path} → {service_url}")

    # Check if this is an SSE stream request
    if path.endswith("/stream") or request.accept_mimetypes.best == "text/event-stream":
        return _proxy_request_sse(service_url)

    return _proxy_request(service_url)


# ── Gateway Health + Service Status ──

@app.route("/api/health")
def health():
    """Gateway health + service connectivity check."""
    services = {}
    for name, url in [("core", CORE_SERVICE), ("simulation", SIM_SERVICE)]:
        try:
            if _client:
                r = _client.get(f"{url}/api/health", timeout=3.0)
                services[name] = {"status": "up", "url": url, "response": r.json()}
            else:
                services[name] = {"status": "unknown", "url": url}
        except Exception:
            services[name] = {"status": "down", "url": url}

    all_up = all(s["status"] == "up" for s in services.values())
    return jsonify({
        "status": "ok" if all_up else "degraded",
        "service": "gateway",
        "port": int(os.getenv("GATEWAY_PORT", 5000)),
        "services": services,
        "routes": {prefix: url for prefix, url in ROUTE_MAP.items()},
    })


if __name__ == "__main__":
    port = int(os.getenv("GATEWAY_PORT", 5000))
    print(f"🌐 EcoSim API Gateway starting on port {port}")
    print(f"   Core Service:       {CORE_SERVICE}")
    print(f"   Simulation Service: {SIM_SERVICE}")
    print(f"   Health: http://localhost:{port}/api/health")
    print()
    for prefix, url in ROUTE_MAP.items():
        print(f"   {prefix}/* → {url}")
    print()
    app.run(host="0.0.0.0", port=port, debug=True)

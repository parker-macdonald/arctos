"""
Main routes: serve the Dioxus SPA.
"""

from pathlib import Path

from flask import Blueprint, send_file, send_from_directory

bp = Blueprint("main", __name__)

# Dioxus SPA is built to frontend/dist; serve it at /app/
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@bp.route("/app/")
@bp.route("/app")
def app_spa():
    """Serve the Dioxus SPA index. SPA lives at /app/."""
    index_path = _FRONTEND_DIST / "index.html"
    if not index_path.exists():
        return "Frontend not built. Run: cd frontend && dx build", 503
    return send_file(index_path, mimetype="text/html")


@bp.route("/app/<path:path>")
def app_static(path):
    """Serve SPA assets (JS, WASM, etc.) from frontend/dist."""
    return send_from_directory(_FRONTEND_DIST, path)

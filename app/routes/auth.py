"""
Authentication routes: logout, check-username, Google OAuth (login + callback only).
Login and register are handled by the SPA and _api.
"""

import os

from flask import (
    Blueprint,
    request,
    redirect,
    flash,
    jsonify,
    session,
    current_app,
    url_for,
)
from flask_login import login_user, logout_user, login_required, current_user
from models import Player, Team
from app.utils.helpers import is_valid_url_username
from authlib.integrations.flask_client import OAuth

bp = Blueprint("auth", __name__, url_prefix="/_api")

# Initialize OAuth (will be configured in app factory)
oauth = OAuth()

_SPA_BASE = "/"


def _frontend_base():
    """Base URL for redirecting to the frontend (no trailing slash)."""
    base = current_app.config.get("EXTERNAL_BASE_URL", "").strip()
    if base:
        return base.rstrip("/")
    return None


def _redirect_to_frontend(path=""):
    """Redirect to the frontend; path should start with / (e.g. /auth/google/choose-account-type)."""
    base = _frontend_base()
    if base:
        return redirect(f"{base}{path}" if path.startswith("/") else f"{base}/{path}")
    return redirect(_SPA_BASE + path.lstrip("/") if path else _SPA_BASE)


def _google_callback_uri():
    """Redirect URI for Google OAuth; must match Google Cloud Console exactly."""
    base = _frontend_base()
    if base:
        script = os.environ.get("SCRIPT_NAME", "").rstrip("/")
        return f"{base}{script}/_api/auth/google/callback"
    return url_for("auth.google_callback", _external=True)


@bp.route("/check-username", methods=["GET"])
def check_username():
    """Check if a username is available (not taken by any player or team)."""
    username = request.args.get("username", "")

    if not username:
        return jsonify({"available": False, "message": "Username is required"})

    if not is_valid_url_username(username):
        return jsonify(
            {
                "available": False,
                "message": "Username must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore.",
            }
        )

    existing_player = Player.query.filter_by(id=username).first()
    existing_team = Team.query.filter_by(id=username).first()

    if existing_player or existing_team:
        return jsonify({"available": False, "message": "Username already exists"})

    return jsonify({"available": True, "message": "Username is available"})


@bp.route("/logout")
@login_required
def logout():
    """User logout."""
    logout_user()
    flash("You have been logged out", "info")
    return _redirect_to_frontend("/")


@bp.route("/auth/google/login")
def google_login():
    """Initiate Google OAuth login."""
    if not current_app.config.get("GOOGLE_CLIENT_ID") or not current_app.config.get(
        "GOOGLE_CLIENT_SECRET"
    ):
        flash(
            "Google sign-in is not configured. Please contact the administrator.",
            "error",
        )
        return _redirect_to_frontend("/")

    redirect_uri = _google_callback_uri()
    google = oauth.google
    return google.authorize_redirect(redirect_uri)


@bp.route("/auth/google/callback")
def google_callback():
    """Handle Google OAuth callback."""
    try:
        google = oauth.google
        token = google.authorize_access_token()

        userinfo_endpoint = getattr(google, "server_metadata", {}).get(
            "userinfo_endpoint"
        )
        if not userinfo_endpoint:
            try:
                google.load_server_metadata()
                userinfo_endpoint = google.server_metadata.get("userinfo_endpoint")
            except Exception:
                userinfo_endpoint = None
        if not userinfo_endpoint:
            raise RuntimeError(
                "Google userinfo endpoint not found in provider metadata"
            )
        resp = google.get(userinfo_endpoint)
        user_info = resp.json()

        google_id = user_info.get("sub")
        email = user_info.get("email", "")
        name = user_info.get("name", email.split("@")[0] if email else "User")

        if not google_id:
            flash("Failed to authenticate with Google", "error")
            return _redirect_to_frontend("/")

        user = Player.query.filter_by(google_id=google_id).first()
        if not user:
            user = Team.query.filter_by(google_id=google_id).first()

        if user:
            login_user(user)
            flash("Successfully logged in with Google!", "success")
            return _redirect_to_frontend("/")

        session["google_oauth_data"] = {
            "google_id": google_id,
            "email": email,
            "name": name,
        }
        return _redirect_to_frontend("/auth/google/choose-account-type")

    except Exception as e:
        flash(f"Error during Google authentication: {str(e)}", "error")
        return _redirect_to_frontend("/")

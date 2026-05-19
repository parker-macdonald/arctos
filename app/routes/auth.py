"""
Authentication routes: logout, check-username, Google OAuth (login + callback only).
Login and register are handled by the SPA and _api.
"""

from flask import (
    Blueprint,
    request,
    redirect,
    flash,
    jsonify,
    session,
    url_for,
)
from flask_login import login_user, logout_user, login_required
from models import Player, Team
from app.utils.helpers import is_valid_url_username
from authlib.integrations.flask_client import OAuth

bp = Blueprint("auth", __name__, url_prefix="/_api")

# Initialize OAuth (will be configured in app factory)
oauth = OAuth()

_SPA_BASE = "/"


def _frontend_path(path: str = "") -> str:
    """Return a same-host frontend path, preserving any deployment subpath."""

    base = request.script_root.rstrip("/") or _SPA_BASE.rstrip("/")
    suffix = f"/{path.lstrip('/')}" if path else ""
    return f"{base}{suffix}" or _SPA_BASE


def _redirect_to_frontend(path: str = ""):
    """Build a Flask redirect response targeting the frontend SPA.

    Args:
        path: Frontend path to append, should begin with ``/``
            (e.g. ``"/auth/google/choose-account-type"``).

    Returns:
        A Flask :func:`~flask.redirect` response.
    """
    return redirect(_frontend_path(path))


def _google_callback_uri() -> str:
    """Return the Google OAuth callback URI registered in Google Cloud Console.

    The callback host/scheme is derived from the current request so the same
    server can answer on multiple public domains, provided each callback URI
    is authorized in Google Cloud Console.

    Returns:
        Absolute callback URL string.
    """
    return f"{request.url_root.rstrip('/')}{url_for('auth.google_callback')}"


@bp.route("/check-username", methods=["GET"])
def check_username():
    """Check username availability.

    ``GET /_api/check-username?username=<value>``

    Validates that the username is URL-safe and not already registered by
    any :class:`~app.models.user.Player` or :class:`~app.models.user.Team`.

    Query Args:
        username: The candidate username string.

    Returns:
        JSON ``{"available": bool, "message": str}``.
    """
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
    """Log out the current user and redirect to the frontend home page.

    ``GET /_api/logout``

    Requires authentication.  Flashes a confirmation message after logout.

    Returns:
        A redirect response to the frontend root ``/``.
    """
    logout_user()
    flash("You have been logged out", "info")
    return _redirect_to_frontend("/")


@bp.route("/auth/google/login")
def google_login():
    """Initiate the Google OAuth 2.0 authorisation code flow.

    ``GET /_api/auth/google/login``

    Redirects the user to Google's consent screen.  Returns an error flash
    and a redirect to the frontend if Google OAuth is not configured.

    Returns:
        A redirect response to Google's authorisation endpoint, or to the
        frontend home page on configuration error.
    """
    if not current_app.config.get("GOOGLE_CLIENT_ID") or not current_app.config.get("GOOGLE_CLIENT_SECRET"):
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
    """Handle the Google OAuth 2.0 callback.

    ``GET /_api/auth/google/callback``

    Exchanges the authorisation code for tokens, fetches user info, and:

    * Logs in an existing account (player or team) if the ``google_id``
      is already registered.
    * Stores the Google profile in the session and redirects to the
      account-type selection page for new users.

    Returns:
        A redirect to the frontend home page on success or error, or to
        ``/auth/google/choose-account-type`` for new Google users.
    """
    try:
        google = oauth.google
        token = google.authorize_access_token()

        userinfo_endpoint = getattr(google, "server_metadata", {}).get("userinfo_endpoint")
        if not userinfo_endpoint:
            try:
                google.load_server_metadata()
                userinfo_endpoint = google.server_metadata.get("userinfo_endpoint")
            except Exception:
                userinfo_endpoint = None
        if not userinfo_endpoint:
            raise RuntimeError("Google userinfo endpoint not found in provider metadata")
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

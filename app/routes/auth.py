"""
Authentication routes (login, register, logout).
"""

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    flash,
    jsonify,
    url_for,
    session,
    current_app,
)
from flask_login import login_user, logout_user, login_required, current_user
from models import Player, Team, db, Tournament, TO
from datetime import datetime
from app.utils.helpers import is_valid_url_username
from authlib.integrations.flask_client import OAuth
import re

bp = Blueprint("auth", __name__)

# Initialize OAuth (will be configured in app factory)
oauth = OAuth()


@bp.route("/login", methods=["GET", "POST"])
def login():
    """User login page (works for both players and teams)."""
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        # Check both Player and Team tables (usernames are unique across both)
        user = Player.query.filter_by(id=username).first()
        if not user:
            user = Team.query.filter_by(id=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Successfully logged in!", "success")
            return redirect("/")
        else:
            flash("Invalid username or password", "error")

    return render_template("login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    """User registration page."""
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        name = request.form["name"]
        user_type = request.form.get("user_type", "player")

        # Validate username is URL-safe
        if not is_valid_url_username(username):
            flash(
                "Username must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore.",
                "error",
            )
            return render_template("register.html", user_type=user_type)

        # Check if username exists in either Player or Team (prevent conflicts)
        existing_player = Player.query.filter_by(id=username).first()
        existing_team = Team.query.filter_by(id=username).first()

        if existing_player or existing_team:
            flash("Username already exists", "error")
            return render_template("register.html", user_type=user_type)

        if user_type == "player":
            user = Player(id=username, name=name)
            user.set_password(password)
        else:
            user = Team(id=username, name=name)
            user.set_password(password)

        if username.lower() in ("jeb", "jebediah"):
            user.profile_photo = "jeb.png"

        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("Account created successfully!", "success")
        return redirect("/")

    user_type = request.args.get("type", "player")
    return render_template("register.html", user_type=user_type)


@bp.route("/check-username", methods=["GET"])
def check_username():
    """Check if a username is available (not taken by any player or team)."""
    username = request.args.get("username", "")

    if not username:
        return jsonify({"available": False, "message": "Username is required"})

    # Check if username is valid format
    if not is_valid_url_username(username):
        return jsonify(
            {
                "available": False,
                "message": "Username must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore.",
            }
        )

    # Check if username exists in either Player or Team
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
    return redirect("/")


@bp.route("/auth/google/login")
def google_login():
    """Initiate Google OAuth login."""
    # Check if Google OAuth is configured
    if not current_app.config.get("GOOGLE_CLIENT_ID") or not current_app.config.get(
        "GOOGLE_CLIENT_SECRET"
    ):
        flash(
            "Google sign-in is not configured. Please contact the administrator.",
            "error",
        )
        return redirect(url_for("auth.login"))

    # Get the redirect URI
    redirect_uri = url_for("auth.google_callback", _external=True)

    # Get OAuth client
    google = oauth.google

    return google.authorize_redirect(redirect_uri)


@bp.route("/auth/google/callback")
def google_callback():
    """Handle Google OAuth callback."""
    try:
        # Get OAuth client
        google = oauth.google
        token = google.authorize_access_token()

        # Get user info from Google (use absolute endpoint from provider metadata)
        userinfo_endpoint = getattr(google, "server_metadata", {}).get(
            "userinfo_endpoint"
        )
        if not userinfo_endpoint:
            # Fallback to OpenID config fetch if not already loaded
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
            return redirect(url_for("auth.login"))

        # Check if user already exists with this Google ID (check both Player and Team)
        user = Player.query.filter_by(google_id=google_id).first()
        if not user:
            user = Team.query.filter_by(google_id=google_id).first()

        if user:
            # Existing user, log them in
            login_user(user)
            flash("Successfully logged in with Google!", "success")
            return redirect("/")

        # New user - store Google info in session and redirect to account type selection
        session["google_oauth_data"] = {
            "google_id": google_id,
            "email": email,
            "name": name,
        }
        return redirect(url_for("auth.google_choose_account_type"))

    except Exception as e:
        flash(f"Error during Google authentication: {str(e)}", "error")
        return redirect(url_for("auth.login"))


@bp.route("/auth/google/choose-account-type", methods=["GET", "POST"])
def google_choose_account_type():
    """Choose account type (Player or Team) for new Google OAuth users."""
    oauth_data = session.get("google_oauth_data")

    if not oauth_data:
        flash("Session expired. Please try signing in again.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        user_type = request.form.get("user_type")
        if user_type not in ["player", "team"]:
            flash("Please select an account type", "error")
            return render_template(
                "google_choose_account_type.html", email=oauth_data.get("email", "")
            )

        # Store user type in session (need to mark session as modified for nested dict changes)
        oauth_data["user_type"] = user_type
        session["google_oauth_data"] = oauth_data
        session.modified = True
        return redirect(url_for("auth.google_complete_profile"))

    return render_template(
        "google_choose_account_type.html", email=oauth_data.get("email", "")
    )


@bp.route("/auth/google/complete-profile", methods=["GET", "POST"])
def google_complete_profile():
    """Complete profile setup for new Google OAuth users."""
    oauth_data = session.get("google_oauth_data")

    if not oauth_data:
        flash("Session expired. Please try signing in again.", "error")
        return redirect(url_for("auth.login"))

    user_type = oauth_data.get("user_type")
    if not user_type:
        # Redirect to account type selection if not set
        return redirect(url_for("auth.google_choose_account_type"))
    email = oauth_data.get("email", "")
    suggested_name = oauth_data.get("name", email.split("@")[0] if email else "User")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        display_name = request.form.get("display_name", "").strip()

        # Validate username
        if not username:
            flash("Username is required", "error")
            return render_template(
                "google_complete_profile.html",
                user_type=user_type,
                suggested_name=suggested_name,
                email=email,
            )

        if not is_valid_url_username(username):
            flash(
                "Username must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore.",
                "error",
            )
            return render_template(
                "google_complete_profile.html",
                user_type=user_type,
                suggested_name=suggested_name,
                email=email,
            )

        # Check if username exists
        existing_player = Player.query.filter_by(id=username).first()
        existing_team = Team.query.filter_by(id=username).first()

        if existing_player or existing_team:
            flash("Username already exists. Please choose a different one.", "error")
            return render_template(
                "google_complete_profile.html",
                user_type=user_type,
                suggested_name=suggested_name,
                email=email,
            )

        # Validate display name
        if not display_name:
            flash("Display name is required", "error")
            return render_template(
                "google_complete_profile.html",
                user_type=user_type,
                suggested_name=suggested_name,
                email=email,
            )

        # Create new user
        if user_type == "player":
            user = Player(
                id=username,
                name=display_name,
                google_id=oauth_data["google_id"],
                email=email,
                profile_photo=(
                    None if username.lower() not in ("jeb", "jebediah") else "jeb.png"
                ),
            )
        else:
            user = Team(
                id=username,
                name=display_name,
                google_id=oauth_data["google_id"],
                email=email,
                profile_photo=(
                    None if username.lower() not in ("jeb", "jebediah") else "jeb.png"
                ),
            )

        db.session.add(user)
        db.session.commit()

        # Clear OAuth data from session
        session.pop("google_oauth_data", None)

        login_user(user)
        flash("Account created and logged in with Google!", "success")
        return redirect("/")

    return render_template(
        "google_complete_profile.html",
        user_type=user_type,
        suggested_name=suggested_name,
        email=email,
    )

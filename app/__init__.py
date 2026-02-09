"""
Tournament site Flask application factory.
"""

from flask import Flask
from flask_login import LoginManager
import os

# Initialize extensions (will be initialized in create_app)
db = None
login_manager = LoginManager()

# Override url_for to handle subpath deployment
from flask import url_for as _url_for


def url_for(endpoint, **values):
    """Custom url_for that handles subpath deployment"""
    url = _url_for(endpoint, **values)
    if "SCRIPT_NAME" in os.environ and not url.startswith(os.environ["SCRIPT_NAME"]):
        url = os.environ["SCRIPT_NAME"] + url
    return url


def create_app(config=None):
    """Application factory."""
    global db

    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    config = config or dict()
    # Default configuration
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key")
    app.config["SQLALCHEMY_DATABASE_URI"] = config.get(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///tournament.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 10MB max file size
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    # For cross-origin SPA (e.g. dx serve on port 8080, Flask on 5006), set ARCTOS_CORS_DEV=1
    # so the session cookie is sent with credentialed requests. SameSite=None requires Secure
    # in production; on localhost some browsers allow it over HTTP.
    if os.environ.get("ARCTOS_CORS_DEV") == "1":
        app.config["SESSION_COOKIE_SAMESITE"] = "None"
        app.config["SESSION_COOKIE_SECURE"] = True
    else:
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Google OAuth configuration
    app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID", "")
    app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    # Handle subpath deployment
    if "SCRIPT_NAME" in os.environ:
        app.config["APPLICATION_ROOT"] = os.environ["SCRIPT_NAME"]

    # Override with custom config if provided
    if config:
        app.config.update(config)

    # Initialize OAuth and Executor (after config is finalized)
    from app.routes.auth import oauth

    oauth.init_app(app)
    from app.routes.tournaments import executor

    executor.init_app(app)
    # Register Google OAuth client
    if app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    # Initialize database
    from models import db as db_instance, init_db

    db = db_instance
    db.init_app(app)
    init_db(db)
    # Ensure tables exist (safe to call on startup)
    try:
        with app.app_context():
            db.create_all()
    except Exception:
        # If creation fails, continue; errors will surface when accessed
        pass

    # Initialize login manager
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import request, redirect, url_for, jsonify

        # For _api routes, return 401 JSON so the SPA gets a proper response instead of
        # a redirect to /login (which would cause CORS errors when the browser follows it).
        if request.path.startswith("/_api"):
            return jsonify({"error": "Not authenticated"}), 401
        return redirect(url_for(login_manager.login_view, next=request.url))

    @login_manager.user_loader
    def load_user(user_id):
        from models import Player, Team

        # Try to load as player first, then team
        user = Player.query.get(user_id)
        if user:
            return user
        return Team.query.get(user_id)

    # Register blueprints
    from app.routes.main import bp as main_bp
    from app.routes.auth import bp as auth_bp
    from app.routes.players import bp as players_bp
    from app.routes.teams import bp as teams_bp
    from app.routes.tournaments import bp as tournaments_bp
    from app.routes.matches import bp as matches_bp
    from app.routes.notes import bp as notes_bp
    from app.routes.registration import bp as registration_bp
    from app.routes._api import bp as _api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(_api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(players_bp)
    app.register_blueprint(teams_bp)
    app.register_blueprint(tournaments_bp)
    app.register_blueprint(matches_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(registration_bp)

    # Register template filters
    from app import filters

    app.register_blueprint(filters.bp)

    # Make custom url_for available in templates
    @app.context_processor
    def inject_url_for():
        return dict(url_for=url_for)

    # CORS for /_api when using dx serve (frontend on different port/protocol than Flask)
    def _cors_allowed_origin(origin_header):
        if not origin_header:
            return None
        origin_lower = origin_header.strip().lower()
        if "localhost" in origin_lower or "127.0.0.1" in origin_lower:
            return origin_header.strip()
        return None

    def _add_cors_headers(response_or_headers, origin):
        if hasattr(response_or_headers, "headers"):
            h = response_or_headers.headers
        else:
            h = response_or_headers
        h["Access-Control-Allow-Origin"] = origin
        h["Access-Control-Allow-Credentials"] = "true"
        h["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        h["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept"
        h["Vary"] = "Origin"

    @app.after_request
    def add_cors_for_api(response):
        from flask import request

        # Add CORS for /_api (including /<tournament>/_api/validate-dsl) and, in dev, for /static/
        is_api = "/_api" in request.path
        is_static_cors = (
            os.environ.get("ARCTOS_CORS_DEV") == "1"
            and request.endpoint == "static"
            and request.path.startswith("/static/")
        )
        if not is_api and not is_static_cors:
            return response
        origin_header = request.headers.get("Origin")
        origin = _cors_allowed_origin(origin_header) if origin_header else None
        if origin:
            _add_cors_headers(response, origin)
        return response

    @app.before_request
    def handle_api_preflight():
        from flask import request, make_response

        # Preflight for /_api (including /<tournament>/_api/validate-dsl) and for /static/ in CORS dev
        is_api = "/_api" in request.path
        is_static_cors = (
            os.environ.get("ARCTOS_CORS_DEV") == "1"
            and request.path.startswith("/static/")
        )
        if request.method != "OPTIONS" or (not is_api and not is_static_cors):
            return None
        origin_header = request.headers.get("Origin")
        origin = _cors_allowed_origin(origin_header) if origin_header else None
        r = make_response("", 204)
        if origin:
            _add_cors_headers(r, origin)
        return r

    # Add cache headers to static file responses (especially images)
    @app.after_request
    def add_cache_headers(response):
        from flask import request

        # Check if this is a static file request
        if response.status_code == 200 and request.endpoint == "static":
            # Cache images and other static assets for 1 hour
            if request.path.startswith("/static/uploads/") or request.path.startswith(
                "/static/"
            ):
                response.cache_control.max_age = 3600
                response.cache_control.public = True
        return response

    # Error handlers
    from app.error_handlers import register_error_handlers

    register_error_handlers(app)

    # On boot: recompute schedule for all tournaments that are not complete (end_date in future or None)
    try:
        with app.app_context():
            from datetime import datetime, timezone
            from models import Tournament
            from app.utils.scheduling import recompute_all_match_times

            now = datetime.now(timezone.utc)
            for t in Tournament.query.all():
                if t.end_date is None:
                    not_complete = True
                else:
                    end_utc = (
                        t.end_date.replace(tzinfo=timezone.utc)
                        if t.end_date.tzinfo is None
                        else t.end_date
                    )
                    not_complete = end_utc >= now
                if not_complete:
                    try:
                        recompute_all_match_times(t.url)
                    except Exception:
                        pass
    except Exception:
        pass

    @app.errorhandler(413)
    def too_large(e):
        from flask import flash, redirect

        flash("File too large. Maximum size is 10MB.", "error")
        return redirect(url_for("main.index"))

    return app

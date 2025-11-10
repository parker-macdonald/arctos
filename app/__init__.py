"""
Tournament site Flask application factory.
"""

from flask import Flask
from flask_login import LoginManager
from flask_socketio import SocketIO
import os

# Initialize extensions (will be initialized in create_app)
db = None
socketio = None
login_manager = LoginManager()

# Override url_for to handle subpath deployment
from flask import url_for as _url_for

def url_for(endpoint, **values):
    """Custom url_for that handles subpath deployment"""
    url = _url_for(endpoint, **values)
    if 'SCRIPT_NAME' in os.environ and not url.startswith(os.environ['SCRIPT_NAME']):
        url = os.environ['SCRIPT_NAME'] + url
    return url


def create_app(config=None):
    """Application factory."""
    global db, socketio

    
    app = Flask(__name__, static_folder='../static', template_folder='../templates')
    
    # Default configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tournament.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 10MB max file size
    
    # Google OAuth configuration
    app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', '')
    app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', '')
    
    # Handle subpath deployment
    if 'SCRIPT_NAME' in os.environ:
        app.config['APPLICATION_ROOT'] = os.environ['SCRIPT_NAME']
    
    # Override with custom config if provided
    if config:
        app.config.update(config)
    
    # Initialize OAuth (after config is finalized)
    from app.routes.auth import oauth
    oauth.init_app(app)
    
    # Register Google OAuth client
    if app.config.get('GOOGLE_CLIENT_ID') and app.config.get('GOOGLE_CLIENT_SECRET'):
        oauth.register(
            name='google',
            client_id=app.config['GOOGLE_CLIENT_ID'],
            client_secret=app.config['GOOGLE_CLIENT_SECRET'],
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={
                'scope': 'openid email profile'
            }
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
    
    # Initialize SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*")
    
    # Initialize login manager
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    
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
    
    app.register_blueprint(main_bp)
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
    
    # Initialize websocket handlers
    from app.routes import websocket
    websocket.init_websocket_handlers(socketio)
    
    # Error handlers
    @app.errorhandler(413)
    def too_large(e):
        from flask import flash, redirect
        flash('File too large. Maximum size is 10MB.', 'error')
        return redirect(url_for('main.index'))
    
    return app


def get_socketio():
    """Get the socketio instance."""
    return socketio


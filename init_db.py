#!/usr/bin/env python3
"""Legacy standalone database initialisation script.

Creates a bare Flask application, wires up SQLAlchemy, and calls
``db.create_all()`` to materialise the full schema in a local SQLite
file (``tournament.db``).

Note:
    Prefer the factory-based ``create_app()`` flow for all new usage.
    This script is retained for one-off local set-up only.
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import uuid

# Create Flask app
app = Flask(__name__)
app.config["SECRET_KEY"] = "your-secret-key-here"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tournament.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Import models and initialize database
from models import db, init_db

db.init_app(app)
init_db(db)

# Import all models after db is initialized
from models import *

# Create all tables
with app.app_context():
    db.create_all()
    print("Database created successfully with new schema!")

from __future__ import annotations

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.models.base import db


class Player(UserMixin, db.Model):
    __tablename__ = "players"

    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    pw_hash = db.Column(db.String(255), nullable=True)  # Nullable for Google OAuth users
    google_id = db.Column(db.String(255), unique=True, nullable=True)  # Google OAuth ID
    email = db.Column(db.String(255), nullable=True)  # Email from Google
    phone = db.Column(db.String(20))
    profile_photo = db.Column(db.String(255))
    bio = db.Column(db.Text)
    location = db.Column(db.String(100))  # Path to uploaded photo

    def set_password(self, password):
        self.pw_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.pw_hash:
            return False
        return check_password_hash(self.pw_hash, password)


class Team(UserMixin, db.Model):
    __tablename__ = "teams"

    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    pw_hash = db.Column(db.String(255), nullable=True)  # Nullable for Google OAuth users
    google_id = db.Column(db.String(255), unique=True, nullable=True)  # Google OAuth ID
    phone = db.Column(db.String(20))
    email = db.Column(db.String(255), nullable=True)  # Updated to match Player, can be from Google
    icon = db.Column(db.Text)  # base64 image
    profile_photo = db.Column(db.String(255))  # Path to uploaded photo
    socials = db.Column(db.Text)
    website = db.Column(db.String(200))
    location = db.Column(db.String(100))
    about = db.Column(db.Text)

    def set_password(self, password):
        self.pw_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.pw_hash:
            return False
        return check_password_hash(self.pw_hash, password)



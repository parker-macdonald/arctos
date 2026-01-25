from __future__ import annotations

from datetime import datetime

from app.models.base import db


class Tournament(db.Model):
    __tablename__ = "tournaments"

    url = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=True)
    location = db.Column(db.String(200))
    num_fields = db.Column(db.Integer, default=1)
    n_max_teams = db.Column(db.Integer)
    max_team_size_roster = db.Column(db.Integer)  # Maximum players on team roster
    max_team_size_field = db.Column(db.Integer)  # Maximum players on field at once
    max_field_size = db.Column(db.Integer)
    team_reg_fee = db.Column(db.Float, default=0.0)
    player_reg_fee = db.Column(db.Float, default=0.0)
    payment_info = db.Column(db.Text)
    published = db.Column(db.Boolean, default=False)
    schedule_published = db.Column(db.Boolean, default=False)
    registration_open = db.Column(db.Boolean, default=False)
    about = db.Column(db.Text)
    terms_link = db.Column(db.String(500))
    head_refs_allowed_list = db.Column(
        db.Text
    )  # comma-separated list of allowed usernames
    head_refs_allow_reffing_teams = db.Column(
        db.Boolean, default=False
    )  # allow reffing teams and their members
    head_refs_allow_anyone = db.Column(
        db.Boolean, default=False
    )  # allow anyone registered
    bracket = db.Column(db.Text)  # TOML string defining bracket visualizations


class TO(db.Model):
    __tablename__ = "tos"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)  # Player or Team ID
    user_type = db.Column(db.String(10), nullable=False)  # 'player' or 'team'
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)


class Field(db.Model):
    __tablename__ = "fields"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    camera = db.Column(
        db.Text
    )  # JSON array of camera URLs (or single URL for backward compatibility)


class Tag(db.Model):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    team = db.Column(db.String(50), db.ForeignKey("teams.id"), nullable=True)

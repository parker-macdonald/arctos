from __future__ import annotations

from datetime import datetime

from app.models.base import db


class TeamRegistration(db.Model):
    __tablename__ = "team_registrations"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    team = db.Column(db.String(50), db.ForeignKey("teams.id"), nullable=False)
    pseudonym = db.Column(db.String(100), nullable=False)  # Team name for this tournament
    status = db.Column(db.String(20), default="CONFIRMED")  # CONFIRMED, CANCELLED
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Payment fields
    paid = db.Column(db.Boolean, default=False)
    amount_paid = db.Column(db.Float, default=0.0)
    paid_at = db.Column(db.DateTime, nullable=True)
    payment_method = db.Column(db.String(50))  # e.g., cash, check, venmo, stripe
    payment_reference = db.Column(db.String(100))  # txn id, check #, etc
    payment_notes = db.Column(db.Text)


class PlayerRegistration(db.Model):
    __tablename__ = "player_registrations"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    player = db.Column(db.String(50), db.ForeignKey("players.id"), nullable=False)
    team = db.Column(db.String(50), db.ForeignKey("teams.id"), nullable=True)  # null for unattached
    jersey_number = db.Column(db.String(10))
    jersey_name = db.Column(db.String(100))  # Player name for this tournament
    status = db.Column(db.String(20), default="PENDING_TEAM_APPROVAL")  # PENDING_TEAM_APPROVAL, CONFIRMED, REJECTED
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Payment fields
    paid = db.Column(db.Boolean, default=False)
    amount_paid = db.Column(db.Float, default=0.0)
    paid_at = db.Column(db.DateTime, nullable=True)
    payment_method = db.Column(db.String(50))
    payment_reference = db.Column(db.String(100))
    payment_notes = db.Column(db.Text)


class TeamInvitation(db.Model):
    __tablename__ = "team_invitations"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    team = db.Column(db.String(50), db.ForeignKey("teams.id"), nullable=False)
    player = db.Column(db.String(50), db.ForeignKey("players.id"), nullable=False)
    status = db.Column(db.String(20), default="PENDING")  # PENDING, ACCEPTED, DECLINED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



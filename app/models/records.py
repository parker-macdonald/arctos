from __future__ import annotations

from datetime import datetime

from app.models.base import db


class Injury(db.Model):
    __tablename__ = "injuries"

    id = db.Column(db.Integer, primary_key=True)
    player = db.Column(db.String(50), db.ForeignKey("players.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    stamp = db.Column(db.DateTime, default=datetime.utcnow)
    show = db.Column(db.Boolean, default=True)
    active = db.Column(db.Boolean, default=True)


class HeadRef(db.Model):
    __tablename__ = "headrefs"

    id = db.Column(db.Integer, primary_key=True)
    player = db.Column(db.String(50), db.ForeignKey("players.id"), nullable=False)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    expdate = db.Column(db.DateTime)


class TeamRecord(db.Model):
    __tablename__ = "teamrecords"

    id = db.Column(db.Integer, primary_key=True)
    team = db.Column(db.String(50), db.ForeignKey("teams.id"), nullable=False)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    ref = db.Column(db.Integer, db.ForeignKey("headrefs.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    stamp = db.Column(db.DateTime, default=datetime.utcnow)
    match = db.Column(db.String(36), db.ForeignKey("matches.uuid"))


class PlayerRecord(db.Model):
    __tablename__ = "playerrecords"

    id = db.Column(db.Integer, primary_key=True)
    player = db.Column(db.String(50), db.ForeignKey("players.id"), nullable=False)
    ref = db.Column(db.Integer, db.ForeignKey("headrefs.id"), nullable=False)
    team = db.Column(db.String(50), db.ForeignKey("teams.id"))
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), default="NOTE")  # NOTE, WARNING, CAUTION, EJECTION
    stamp = db.Column(db.DateTime, default=datetime.utcnow)
    match = db.Column(db.String(36), db.ForeignKey("matches.uuid"))



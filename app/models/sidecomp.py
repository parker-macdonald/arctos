from __future__ import annotations

from datetime import datetime

from app.models.base import db


class SideComp(db.Model):
    __tablename__ = "sidecomps"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)


class SideCompResult(db.Model):
    __tablename__ = "sidecompresults"

    id = db.Column(db.Integer, primary_key=True)
    comp = db.Column(db.Integer, db.ForeignKey("sidecomps.id"), nullable=False)
    player = db.Column(db.String(50), db.ForeignKey("players.id"), nullable=False)
    scanner_id = db.Column(db.Integer)
    stamp = db.Column(db.DateTime, default=datetime.utcnow)

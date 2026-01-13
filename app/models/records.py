from __future__ import annotations

from datetime import datetime, timezone

from app.models.base import db


class Injury(db.Model):
    __tablename__ = "injuries"

    id = db.Column(db.Integer, primary_key=True)
    player = db.Column(db.String(50), db.ForeignKey("players.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    stamp = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    show = db.Column(db.Boolean, default=True)
    active = db.Column(db.Boolean, default=True)


class HeadRef(db.Model):
    __tablename__ = "headrefs"

    id = db.Column(db.Integer, primary_key=True)
    player = db.Column(db.String(50), db.ForeignKey("players.id"), nullable=False)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    expdate = db.Column(db.DateTime)

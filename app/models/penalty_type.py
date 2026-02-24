from __future__ import annotations

from app.models.base import db


class PenaltyType(db.Model):
    __tablename__ = "penalty_types"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(6), nullable=False)
    desc = db.Column(db.Text)

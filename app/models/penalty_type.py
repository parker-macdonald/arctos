from __future__ import annotations

from app.models.base import db


class PenaltyType(db.Model):
    __tablename__ = "penalty_types"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(
        db.String(100), db.ForeignKey("tournaments.url"), nullable=True
    )
    league_id = db.Column(
        db.String(100), db.ForeignKey("leagues.url"), nullable=True
    )
    name = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(6), nullable=False)
    desc = db.Column(db.Text)

    league = db.relationship(
        "League",
        backref="penalty_types",
        foreign_keys=[league_id],
    )

    __table_args__ = (
        db.CheckConstraint(
            "(event IS NOT NULL AND league_id IS NULL) OR "
            "(event IS NULL AND league_id IS NOT NULL)",
            name="ck_penalty_type_event_league_mutual_exclusive",
        ),
    )

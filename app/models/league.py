"""League model."""

from __future__ import annotations

from app.models.base import db


class League(db.Model):
    """A league. Standalone entity; TOs create a new league for each season."""

    __tablename__ = "leagues"

    url = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    about = db.Column(db.Text)
    published = db.Column(db.Boolean, default=False, nullable=False)

    registrable_config_id = db.Column(
        db.Integer,
        db.ForeignKey("registrable_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    registrable_config = db.relationship(
        "RegistrableConfig",
        backref="leagues",
        foreign_keys=[registrable_config_id],
    )

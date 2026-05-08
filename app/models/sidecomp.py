"""Side competitions.

Defines :class:`SideComp` - the competition itself, scoped to a single
tournament - and :class:`SideCompResult`, one row per player entry.
Independent of the main match / point flow.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.base import db
from app.models.constants import (
    SHORT_LABEL_LEN,
    SHORT_NAME_LEN,
    URL_SLUG_LEN,
    USER_ID_LEN,
)


class SideComp(db.Model):
    """A side competition at a tournament.

    Attributes:
        id: Auto-increment primary key.
        event: Tournament URL slug this side competition belongs to.
        name: Display name of the competition.
        type: Competition type identifier string.
    """

    __tablename__ = "sidecomps"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(URL_SLUG_LEN), db.ForeignKey("tournaments.url"), nullable=False)
    name = db.Column(db.String(SHORT_NAME_LEN), nullable=False)
    type = db.Column(db.String(SHORT_LABEL_LEN), nullable=False)


class SideCompResult(db.Model):
    """A single player's result entry in a side competition.

    Attributes:
        id: Auto-increment primary key.
        comp: FK to the parent :class:`SideComp`.
        player: ID of the participating player.
        scanner_id: Optional scanner device ID used for automated result
            capture.
        stamp: Timestamp when the result was recorded.
    """

    __tablename__ = "sidecompresults"

    id = db.Column(db.Integer, primary_key=True)
    comp = db.Column(db.Integer, db.ForeignKey("sidecomps.id"), nullable=False)
    player = db.Column(db.String(USER_ID_LEN), db.ForeignKey("players.id"), nullable=False)
    scanner_id = db.Column(db.Integer)
    stamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

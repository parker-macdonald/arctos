"""SQLAlchemy models for side competitions, their registrations, and results."""

from __future__ import annotations


from app.domain.enums import SideCompType
from app.models.base import db
from app.utils.datetime_helpers import now_utc_naive
from app.models.constants import (
    SHORT_NAME_LEN,
    URL_SLUG_LEN,
    USER_ID_LEN,
)


class SideComp(db.Model):
    """A side competition (e.g. dueling, chain/breaking) at a tournament.

    Attributes:
        id: Auto-increment primary key.
        event: Tournament URL slug this side competition belongs to.
        name: Display name of the competition.
        type: One of :class:`SideCompType`.
        description: Optional free-form description of the side competition.
        registration_open: When ``True``, players can self-register; when
            ``False`` (default), only TO can add registrants.
        created_at: Timestamp when the side competition was created.
    """

    __tablename__ = "sidecomps"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(URL_SLUG_LEN), db.ForeignKey("tournaments.url"), nullable=False)
    name = db.Column(db.String(SHORT_NAME_LEN), nullable=False)
    type = db.Column(db.Enum(SideCompType), nullable=False)
    description = db.Column(db.Text, nullable=True)
    registration_open = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime,
        default=now_utc_naive,
        nullable=False,
    )


class SideCompRegistration(db.Model):
    """A player's registration in a side competition.

    Attributes:
        id: Auto-increment primary key.
        comp: FK to the parent :class:`SideComp`.
        player: FK to the registering player.
        entry_number: 1-indexed sequential entry number assigned at
            registration time, unique within a comp. Numbers are not reused
            after a deregistration.
        registered_at: Timestamp when the registration was created.
        registered_by_to: ``True`` when the row was created via TO registration,
            ``False`` for player self-registration.
    """

    __tablename__ = "sidecomp_registrations"

    id = db.Column(db.Integer, primary_key=True)
    comp = db.Column(db.Integer, db.ForeignKey("sidecomps.id"), nullable=False)
    player = db.Column(db.String(USER_ID_LEN), db.ForeignKey("players.id"), nullable=False)
    entry_number = db.Column(db.Integer, nullable=False)
    registered_at = db.Column(
        db.DateTime,
        default=now_utc_naive,
        nullable=False,
    )
    registered_by_to = db.Column(db.Boolean, default=False, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("comp", "player", name="uq_sidecomp_registrations_comp_player"),
        db.UniqueConstraint("comp", "entry_number", name="uq_sidecomp_registrations_comp_entry_number"),
    )


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
    stamp = db.Column(db.DateTime, default=now_utc_naive)

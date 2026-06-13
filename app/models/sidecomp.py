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


class SideCompCategory(db.Model):
    """A TO-defined category within a side competition.

    A side competition may have zero or more categories (e.g. "Novice", "Pro").
    When a comp has categories, a player must choose one at registration; when it
    has none, registration is uncategorized and everyone competes as one group.

    Attributes:
        id: Auto-increment primary key.
        comp: FK to the parent :class:`SideComp`.
        name: Display name of the category, unique within the comp.
        created_at: Timestamp when the category was created.
    """

    __tablename__ = "sidecomp_categories"

    id = db.Column(db.Integer, primary_key=True)
    comp = db.Column(db.Integer, db.ForeignKey("sidecomps.id"), nullable=False)
    name = db.Column(db.String(SHORT_NAME_LEN), nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=now_utc_naive,
        nullable=False,
    )

    __table_args__ = (db.UniqueConstraint("comp", "name", name="uq_sidecomp_categories_comp_name"),)


class SideCompEntryNumber(db.Model):
    """A player's tournament-stable side competition entry number.

    A player is assigned one entry number per tournament, the first time they
    register for any side competition in that tournament. The number is shared
    across every side competition the player enters in that tournament, so a
    competitor carries a single number (think bib/scoresheet) regardless of how
    many side competitions they join.

    Attributes:
        id: Auto-increment primary key.
        tournament_url: URL slug of the tournament the number is scoped to.
        player: FK to the player the number belongs to.
        entry_number: 1-indexed entry number, unique within the tournament.
            Numbers are not reused after a deregistration.
        created_at: Timestamp when the number was assigned.
    """

    __tablename__ = "sidecomp_entry_numbers"

    id = db.Column(db.Integer, primary_key=True)
    tournament_url = db.Column(db.String(URL_SLUG_LEN), db.ForeignKey("tournaments.url"), nullable=False)
    player = db.Column(db.String(USER_ID_LEN), db.ForeignKey("players.id"), nullable=False)
    entry_number = db.Column(db.Integer, nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=now_utc_naive,
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint("tournament_url", "player", name="uq_sidecomp_entry_numbers_tournament_player"),
        db.UniqueConstraint("tournament_url", "entry_number", name="uq_sidecomp_entry_numbers_tournament_entry_number"),
    )


class SideCompRegistration(db.Model):
    """A player's registration in a side competition.

    The player's displayed entry number is not stored here; it lives in
    :class:`SideCompEntryNumber`, scoped to the tournament so it is consistent
    across every side competition the player enters.

    Attributes:
        id: Auto-increment primary key.
        comp: FK to the parent :class:`SideComp`.
        player: FK to the registering player.
        category: FK to the chosen :class:`SideCompCategory`, or ``None`` when the
            comp has no categories (or for rows predating categories).
        registered_at: Timestamp when the registration was created.
        registered_by_to: ``True`` when the row was created via TO registration,
            ``False`` for player self-registration.
    """

    __tablename__ = "sidecomp_registrations"

    id = db.Column(db.Integer, primary_key=True)
    comp = db.Column(db.Integer, db.ForeignKey("sidecomps.id"), nullable=False)
    player = db.Column(db.String(USER_ID_LEN), db.ForeignKey("players.id"), nullable=False)
    category = db.Column(db.Integer, db.ForeignKey("sidecomp_categories.id"), nullable=True)
    registered_at = db.Column(
        db.DateTime,
        default=now_utc_naive,
        nullable=False,
    )
    registered_by_to = db.Column(db.Boolean, default=False, nullable=False)

    __table_args__ = (db.UniqueConstraint("comp", "player", name="uq_sidecomp_registrations_comp_player"),)


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

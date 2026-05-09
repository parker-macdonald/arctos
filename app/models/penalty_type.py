"""TO-defined penalty categories.

Defines :class:`PenaltyType` - the named penalty entries that head
refs attach to :class:`~app.models.match.MatchNote` records during a
match.

Each type is scoped to either a tournament or a league (never
both), the same scope-column invariant the registration tables use.
"""

from __future__ import annotations

from app.models.base import db
from app.models.constants import HEX_COLOR_LEN, SHORT_LABEL_LEN, URL_SLUG_LEN


class PenaltyType(db.Model):
    """A named penalty category defined by a TO for an event or league.

    Penalty types appear in the head-ref interface so refs can attach
    structured penalty records to :class:`~app.models.match.MatchNote`
    entries.  Either ``event`` or ``league_id`` must be set (not both).

    Attributes:
        id: Auto-increment primary key.
        event: Tournament URL slug this type belongs to, or ``None`` for
            league-level types.
        league_id: League URL slug this type belongs to, or ``None`` for
            event-level types.
        name: Short display name (e.g. ``"Yellow card"``).
        color: Six-character hex colour code for UI rendering (no ``#``).
        desc: Optional longer description of when to use this penalty.
    """

    __tablename__ = "penalty_types"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(URL_SLUG_LEN), db.ForeignKey("tournaments.url"), nullable=True)
    league_id = db.Column(db.String(URL_SLUG_LEN), db.ForeignKey("leagues.url"), nullable=True)
    name = db.Column(db.String(SHORT_LABEL_LEN), nullable=False)
    color = db.Column(db.String(HEX_COLOR_LEN), nullable=False)
    desc = db.Column(db.Text)

    league = db.relationship(
        "League",
        backref="penalty_types",
        foreign_keys=[league_id],
    )

    __table_args__ = (
        db.CheckConstraint(
            "(event IS NOT NULL AND league_id IS NULL) OR (event IS NULL AND league_id IS NOT NULL)",
            name="ck_penalty_type_event_league_mutual_exclusive",
        ),
    )
